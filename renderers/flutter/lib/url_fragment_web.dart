import 'package:web/web.dart' as web;

/// Replaces this history entry with the same address and no fragment.
void clearUrlFragment() {
  final location = web.window.location;
  web.window.history.replaceState(
    null,
    '',
    '${location.pathname}${location.search}',
  );
}
