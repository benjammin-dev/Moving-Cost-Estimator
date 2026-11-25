"""Staff-only API for the Movers pages. Anyone can register an account, so
none of this is open to regular users."""

from django.db.models import Count, Q
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ImportRun, Mover
from .serializers import ImportRunSerializer, MoverCreateSerializer, MoverSerializer, MoverUpdateSerializer
from .services import ImportAlreadyRunning, start_import


class MoverPagination(PageNumberPagination):
    page_size = 25


def search_filter(query):
    """Name, DBA, city or UTC permit; or a USDOT / MC number ("8257", "MC59073")."""
    query = query.strip()
    match = (
        Q(name__icontains=query) | Q(dba_name__icontains=query) | Q(city__icontains=query)
        | Q(utc_permit_number__iexact=query)
    )
    digits = query.upper().removeprefix("MC").lstrip("- ").lstrip("0")
    if digits.isdigit() and len(digits) <= 10:
        match |= Q(mc_number=digits) | Q(usdot_number=int(digits))
    return match


class MoverList(generics.ListCreateAPIView):
    """GET /api/movers/?search=&status=&claimed=true|false&authority=active|lapsed
    &utc=active|not_permitted|none&source=fmcsa|utc|staff&page=
    POST /api/movers/ adds a mover (staff)."""
    permission_classes = [IsAdminUser]
    pagination_class = MoverPagination

    def get_serializer_class(self):
        return MoverCreateSerializer if self.request.method == "POST" else MoverSerializer

    def create(self, request, *args, **kwargs):
        serializer = MoverCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mover = serializer.save()
        return Response(MoverSerializer(mover).data, status=status.HTTP_201_CREATED)

    def get_queryset(self):
        qs = Mover.objects.all()
        params = self.request.query_params
        if params.get("search", "").strip():
            qs = qs.filter(search_filter(params["search"]))
        if params.get("status") in Mover.Status.values:
            qs = qs.filter(status=params["status"])
        if params.get("claimed") in ("true", "false"):
            qs = qs.filter(claimed=params["claimed"] == "true")
        if params.get("authority") == "active":
            qs = qs.filter(fmcsa_authority_active=True)
        elif params.get("authority") == "lapsed":
            qs = qs.filter(fmcsa_authority_active=False)
        if params.get("utc") == "active":
            qs = qs.filter(utc_status="Active")
        elif params.get("utc") == "not_permitted":
            qs = qs.exclude(utc_status="").exclude(utc_status="Active")
        elif params.get("utc") == "none":
            qs = qs.filter(utc_status="")
        if params.get("source") in Mover.Source.values:
            qs = qs.filter(source=params["source"])
        return qs.order_by("name", "id")


class MoverDetail(generics.RetrieveUpdateAPIView):
    """GET or PATCH /api/movers/<id>/. PATCH takes utc_permit_number and status."""
    queryset = Mover.objects.all()
    permission_classes = [IsAdminUser]
    http_method_names = ["get", "patch", "head", "options"]

    def get_serializer_class(self):
        return MoverUpdateSerializer if self.request.method == "PATCH" else MoverSerializer

    def update(self, request, *args, **kwargs):
        mover = self.get_object()
        serializer = MoverUpdateSerializer(mover, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MoverSerializer(mover).data)


class MoverSummary(APIView):
    """Counts for the summary tiles, plus the latest import of each kind."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        counts = Mover.objects.aggregate(
            total=Count("id"),
            unverified=Count("id", filter=Q(status=Mover.Status.UNVERIFIED)),
            verified=Count("id", filter=Q(status=Mover.Status.VERIFIED)),
            inactive=Count("id", filter=Q(status=Mover.Status.INACTIVE)),
            claimed=Count("id", filter=Q(claimed=True)),
            bookable=Count("id", filter=Q(status=Mover.Status.VERIFIED) & Q(utc_permit_number__isnull=False) & ~Q(utc_permit_number="")),
            utc_active=Count("id", filter=Q(utc_status="Active")),
        )
        latest = {}
        for kind in ImportRun.Kind.values:
            run = ImportRun.objects.filter(kind=kind).first()
            latest[kind] = ImportRunSerializer(run).data if run else None
        return Response({"counts": counts, "latest_imports": latest})


class ImportRuns(APIView):
    """GET: the 10 most recent imports. POST {"kind": "fmcsa"|"utc", "dry_run": bool}:
    start one. It runs in the background; poll the summary for finished_at."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response(ImportRunSerializer(ImportRun.objects.all()[:10], many=True).data)

    def post(self, request):
        kind = request.data.get("kind", ImportRun.Kind.FMCSA)
        if kind not in ImportRun.Kind.values:
            return Response({"kind": [f"Choose one of: {', '.join(ImportRun.Kind.values)}."]}, status=status.HTTP_400_BAD_REQUEST)
        dry_run = request.data.get("dry_run") in (True, "true", "1", 1)
        try:
            run = start_import(kind, dry_run=dry_run, triggered_by=request.user)
        except ImportAlreadyRunning:
            return Response({"detail": "That import is already running. Wait for it to finish."}, status=status.HTTP_409_CONFLICT)
        run.refresh_from_db()
        return Response(ImportRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)
