"""Staff-only API for the Movers pages. Anyone can register an account, so
none of this is open to regular users."""

from django.db.models import Count, Q
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .fmcsa import FMCSAError
from .models import ImportRun, Mover
from .serializers import ImportRunSerializer, MoverSerializer, MoverUpdateSerializer
from .services import run_import

IMPORT_STATE = "WA"


class MoverPagination(PageNumberPagination):
    page_size = 25


def search_filter(query):
    """Name, DBA or city; or a USDOT / MC number ("8257", "MC59073")."""
    query = query.strip()
    match = Q(name__icontains=query) | Q(dba_name__icontains=query) | Q(city__icontains=query)
    digits = query.upper().removeprefix("MC").lstrip("- ").lstrip("0")
    if digits.isdigit() and len(digits) <= 10:
        match |= Q(mc_number=digits) | Q(usdot_number=int(digits))
    return match


class MoverList(generics.ListAPIView):
    """GET /api/movers/?search=&status=&claimed=true|false&authority=active|lapsed&page="""
    serializer_class = MoverSerializer
    permission_classes = [IsAdminUser]
    pagination_class = MoverPagination

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
        return qs.order_by("name", "usdot_number")


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
    """Counts for the summary tiles, plus the latest import."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        counts = Mover.objects.aggregate(
            total=Count("id"),
            unverified=Count("id", filter=Q(status=Mover.Status.UNVERIFIED)),
            verified=Count("id", filter=Q(status=Mover.Status.VERIFIED)),
            inactive=Count("id", filter=Q(status=Mover.Status.INACTIVE)),
            claimed=Count("id", filter=Q(claimed=True)),
            bookable=Count("id", filter=Q(status=Mover.Status.VERIFIED) & Q(utc_permit_number__isnull=False) & ~Q(utc_permit_number="")),
        )
        latest = ImportRun.objects.first()
        return Response({
            "counts": counts,
            "latest_import": ImportRunSerializer(latest).data if latest else None,
        })


class ImportRuns(APIView):
    """GET: the 10 most recent imports. POST {"dry_run": bool}: run one now."""
    permission_classes = [IsAdminUser]

    def get(self, request):
        return Response(ImportRunSerializer(ImportRun.objects.all()[:10], many=True).data)

    def post(self, request):
        dry_run = request.data.get("dry_run") in (True, "true", "1", 1)
        try:
            run, _ = run_import(state=IMPORT_STATE, dry_run=dry_run, triggered_by=request.user)
        except FMCSAError as err:
            return Response(
                {"detail": f"The import couldn't reach FMCSA ({err}). Try again in a few minutes."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response(ImportRunSerializer(run).data, status=status.HTTP_201_CREATED)
