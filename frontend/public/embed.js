/*
 * Moving quote widget: embed helper for the host site.
 *
 *   <iframe src="https://YOUR-APP/widget" title="Moving quote" data-moving-quote
 *           style="width:100%;height:1400px;border:0"></iframe>
 *   <script src="https://YOUR-APP/embed.js" async></script>
 *
 * The widget posts its content height (see useReportHeight in src/hooks.js)
 * and this sizes the matching iframe to fit, so there's no inner scrollbar.
 * The inline height is only the fallback until the first message arrives.
 * A message is used only if it comes from one of the data-moving-quote
 * iframes and from that iframe's own origin.
 */
(function () {
  if (window.__movingQuoteEmbed) return
  window.__movingQuoteEmbed = true

  var MESSAGE = "moving-quote:resize"
  var MAX_HEIGHT = 20000

  window.addEventListener("message", function (event) {
    var data = event.data
    if (!data || data.type !== MESSAGE || typeof data.height !== "number" || !isFinite(data.height)) return

    var frames = document.querySelectorAll("iframe[data-moving-quote]")
    for (var i = 0; i < frames.length; i++) {
      var frame = frames[i]
      if (frame.contentWindow !== event.source) continue
      var origin
      try {
        origin = new URL(frame.src, window.location.href).origin
      } catch {
        return
      }
      if (event.origin !== origin) return
      var height = Math.min(Math.max(Math.round(data.height), 0), MAX_HEIGHT)
      frame.style.height = height + "px"
      return
    }
  })
})()
