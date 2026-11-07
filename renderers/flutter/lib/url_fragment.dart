// Removing the `#key=` fragment from the address bar, where there is one.
//
// On the web the fragment is replaced in the history entry, so the key is not
// in the URL a traveller copies or the page a reload restores. Elsewhere there
// is no address bar and nothing to do.

export 'url_fragment_stub.dart'
    if (dart.library.js_interop) 'url_fragment_web.dart';
