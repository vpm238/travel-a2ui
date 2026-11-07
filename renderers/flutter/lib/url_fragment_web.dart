import 'package:web/web.dart' as web;

/// Replaces this history entry with the same address and no fragment.
///
/// The entry's state is kept: Flutter's router stores its own bookkeeping
/// there, and replacing it with `null` makes the router throw.
void clearUrlFragment() {
  final location = web.window.location;
  web.window.history.replaceState(
    web.window.history.state,
    '',
    '${location.pathname}${location.search}',
  );
}
