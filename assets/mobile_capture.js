/* StockVision AI - mobile camera capture support.
 * dash.dcc.Upload doesn't expose the HTML `capture` attribute, so we patch
 * it onto the hidden <input type="file"> inside the element tagged
 * id="upload-camera" once it exists in the DOM. This makes mobile browsers
 * (Chrome/Safari on Android & iOS) open the camera directly instead of the
 * generic file picker. The separate "upload-files" control is left alone so
 * users can still pick existing photos / PDFs from their gallery or files app.
 */
(function () {
  function patchCameraInput() {
    var container = document.getElementById("upload-camera");
    if (!container) return;
    var input = container.querySelector('input[type="file"]');
    if (input && !input.hasAttribute("capture")) {
      input.setAttribute("capture", "environment");
      input.setAttribute("accept", "image/*");
    }
  }

  var observer = new MutationObserver(patchCameraInput);
  observer.observe(document.body, { childList: true, subtree: true });
  document.addEventListener("DOMContentLoaded", patchCameraInput);
  patchCameraInput();
})();
