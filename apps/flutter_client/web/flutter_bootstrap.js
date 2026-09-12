// Boot the engine from *this* origin, not from gstatic.com.
//
// By default Flutter web fetches CanvasKit — several megabytes of WebAssembly —
// from `https://www.gstatic.com/flutter-canvaskit/<engine hash>/`. The build
// already puts an identical copy in `canvaskit/` beside this file and then does
// not use it.
//
// Three reasons that default is wrong here, and the first is the one that made
// it visible: on a network that does not allow gstatic.com the page loads, the
// script runs, no error is reported, and nothing ever renders. The second is
// that a deployment claiming to be one self-contained service should not need a
// third party to be reachable before it can draw anything. The third is that
// every visitor's browser announces itself to Google on every cold load, which
// is not a thing to do quietly on someone else's behalf.
{{flutter_js}}
{{flutter_build_config}}

_flutter.loader.load({
  config: {
    // Relative, so it resolves against the `<base href>` — which is `/flutter/`
    // in the deployed app and `/` when this is served on its own.
    canvasKitBaseUrl: 'canvaskit/',
  },
});
