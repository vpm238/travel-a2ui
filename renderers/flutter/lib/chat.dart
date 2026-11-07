// The conversation: prose and surfaces, interleaved as they arrive.
//
// Interleaved rather than grouped, because a turn is a sequence of parts. The
// model says a sentence, draws, and says another — and putting all the prose
// above all the surfaces would put "want me to hold one?" above the thing being
// held.
//
// Two rules the React client also follows, and neither is decoration:
//
//   Only the newest surface accepts input. Everything above it answered a
//   question the conversation has moved past, and pressing it would answer a
//   settled question against a data model describing a trip that no longer
//   exists. Spent surfaces stay on screen — they are the record of what was
//   chosen — and go quiet.
//
//   A press is sent as an *action*, never as a sentence. The client does not
//   compose "[interface] select_flight (id: …)"; it sends the action A2UI
//   itself produced. What that means is the agent's to decide, which is why
//   this client can exist at all without being taught anything.

import 'package:a2ui_core/a2ui_core.dart';
import 'package:a2ui_flutter/a2ui_flutter.dart';
import 'package:flutter/material.dart';

import 'api.dart';

/// One thing in the feed.
sealed class Part {}

class SaidByYou extends Part {
  SaidByYou(this.text);
  final String text;
}

class SaidByAgent extends Part {
  SaidByAgent(this.buffer);
  final StringBuffer buffer;
  String get text => buffer.toString();
}

class Drawn extends Part {
  Drawn(this.surfaceId);
  final String surfaceId;
}

class Failed extends Part {
  Failed(this.message);
  final String message;
}

class ChatScreen extends StatefulWidget {
  const ChatScreen({
    super.key,
    required this.api,
    required this.meta,
    required this.catalog,
  });

  final TravelApi api;
  final ServerMeta meta;
  final CatalogImplementation catalog;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

/// Surfaces that live somewhere of their own.
///
/// The server's `STANDING_SURFACES`, and the only thing this client needs to
/// know about them: they are replaced rather than appended, so they are a
/// panel and not a message.
const Set<String> _standing = {'sidebar', 'home'};

class _ChatScreenState extends State<ChatScreen> {
  late final MessageProcessor<ComponentImplementation> _processor;
  final _parts = <Part>[];
  final _composer = TextEditingController();
  final _scroll = ScrollController();

  String? _sessionId;

  /// The last turn's receipt: where the conversation is, and what has been
  /// decided. Kept, never read — see `resume` in `api.dart`.
  Map<String, dynamic>? _resume;
  bool _busy = false;

  /// Errors the processor reported, to forward with the next request.
  final _unsentErrors = <Map<String, dynamic>>[];

  /// The surface a press is still allowed to come from.
  String? _liveSurface;

  /// The standing panel, once the server has drawn one.
  String? _panel;

  /// Whether the panel changed since the traveller last opened it.
  bool _panelChanged = false;

  @override
  void initState() {
    super.initState();
    _processor = MessageProcessor<ComponentImplementation>(
      catalogs: [widget.catalog],
      defaultVersion: A2uiProtocolVersion.v1_0,
      onAction: _onAction,
      onError: (error) => _report(ErrorMessage(version: '1.0', error: error)),
    );
    // Which surfaces exist is the SDK's to say: a card joins the conversation
    // when it is created and leaves when it is deleted.
    _processor.model.onSurfaceCreated.subscribe((surface) => _created(surface.id));
    _processor.model.onSurfaceDeleted.subscribe(_deleted);
  }

  void _report(ErrorMessage error) {
    _unsentErrors.add(error.toJson());
    if (_unsentErrors.length > 20) _unsentErrors.removeAt(0);
  }

  /// What every request says on the renderer's behalf.
  Map<String, dynamic> _metadata() {
    final capabilities = _processor.getRendererCapabilities(
      const CapabilitiesOptions(versions: [A2uiProtocolVersion.v1_0]),
    );
    final dataModel = _processor.getRendererDataModel(version: A2uiProtocolVersion.v1_0);
    return {
      'a2uiRendererCapabilities': capabilities.toJson(),
      if (dataModel != null) 'a2uiRendererDataModel': dataModel,
    };
  }

  void _created(String surfaceId) {
    if (!mounted) return;
    setState(() {
      if (_standing.contains(surfaceId)) {
        _panel = surfaceId;
        _panelChanged = true;
      } else if (!_parts.whereType<Drawn>().any((part) => part.surfaceId == surfaceId)) {
        _parts.add(Drawn(surfaceId));
      }
    });
    _toBottom();
  }

  void _deleted(String surfaceId) {
    if (!mounted) return;
    setState(() {
      _parts.removeWhere((part) => part is Drawn && part.surfaceId == surfaceId);
      if (_panel == surfaceId) _panel = null;
    });
  }

  @override
  void dispose() {
    _composer.dispose();
    _scroll.dispose();
    super.dispose();
  }

  /// Somebody pressed something. That is their turn.
  ///
  /// Sent as the v1.0 `ActionMessage` the SDK defines. What the traveller set
  /// on a surface created with `sendDataModel` goes in the request's
  /// `a2uiRendererDataModel`, which `getRendererDataModel` builds.
  void _onAction(A2uiRendererAction action) {
    if (_busy) return;
    // A press on the panel is a request to re-open a decision, and deciding
    // happens in the conversation — so it is allowed through even though the
    // panel is not the live surface. Without this the only button the panel is
    // permitted to draw was the one button this client silently ignored.
    if (action.surfaceId != _liveSurface && !_standing.contains(action.surfaceId)) return;

    _send(action: ActionMessage(version: '1.0', action: action).toJson());
  }

  Future<void> _send({String message = '', Map<String, dynamic>? action}) async {
    if (_busy) return;
    if (message.isEmpty && action == null) return;

    final errors = List<Map<String, dynamic>>.of(_unsentErrors);
    _unsentErrors.clear();
    setState(() {
      _busy = true;
      if (message.isNotEmpty) _parts.add(SaidByYou(message));
    });
    _composer.clear();
    _toBottom();

    SaidByAgent? speaking;

    try {
      final stream = widget.api.chat(
        message: message,
        a2ui: [...errors, if (action != null) action],
        metadata: _metadata(),
        sessionId: _sessionId,
        resume: _resume,
        surfaces: [for (final surface in _processor.model.allSurfaces) surface.id],
      );

      await for (final event in stream) {
        switch (event.type) {
          case 'session':
            _sessionId = event.raw['sessionId'] as String?;

          case 'start':
            // The server names this turn's card; a press is allowed from it.
            _liveSurface = event.raw['surfaceId'] as String?;

          case 'resume':
            _resume = {
              'interactionId': event.raw['interactionId'],
              'trip': event.raw['trip'],
              'setup': event.raw['setup'],
            };

          case 'text':
            setState(() {
              if (speaking == null) {
                speaking = SaidByAgent(StringBuffer());
                _parts.add(speaking!);
              }
              speaking!.buffer.write(event.delta);
            });
            _toBottom();

          case 'ui':
            _draw(event);
            // A new tool round starts a new paragraph: two sentences either
            // side of a tool call are two sentences, and concatenated they read
            // as a typo.
            speaking = null;

          case 'error':
            setState(() => _parts.add(Failed(event.raw['message']?.toString() ?? 'Something failed.')));

          case 'done':
            break;
        }
      }
    } catch (error) {
      setState(() => _parts.add(Failed('$error')));
    } finally {
      if (mounted) setState(() => _busy = false);
      _toBottom();
    }
  }

  void _draw(TurnEvent event) {
    // A message the processor refuses is shown, forwarded to the agent with the
    // next request, and the rest still apply. Which cards exist follows from
    // `onSurfaceCreated` and `onSurfaceDeleted`.
    final refused = _processor.processMessagesWithErrors(event.messages);
    for (final error in refused) {
      _report(error);
      setState(() => _parts.add(Failed('That surface could not be read: ${error.error.message}')));
    }
    if (_standing.contains(event.surfaceId) && _processor.model.getSurface(event.surfaceId) != null) {
      setState(() => _panelChanged = true);
    }
  }

  void _toBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOut,
      );
    });
  }

  /// Opens the trip: the agent's panel, in a sheet over the conversation.
  ///
  /// A phone has no room for a sidebar, and a strip above the feed squeezed the
  /// conversation into whatever was left. A cart is the shape people already
  /// know for "what I have chosen so far": a bar that says so, and a tap to
  /// review it. What is inside is the agent's own surface, drawn by the SDK —
  /// this client only decides where it sits.
  Future<void> _openTrip() async {
    final panelId = _panel;
    final panel = panelId == null ? null : _processor.model.getSurface(panelId);
    if (panel == null) return;
    setState(() => _panelChanged = false);
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (context) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.72,
        minChildSize: 0.35,
        maxChildSize: 0.95,
        builder: (context, scroll) => ListView(
          controller: scroll,
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          children: [A2uiSurface(surface: panel)],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final provenance = widget.meta.provenance;
    final scheme = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    final hasTrip = _panel != null && _processor.model.getSurface(_panel!) != null;
    return Scaffold(
      backgroundColor: scheme.surfaceContainerLowest,
      appBar: AppBar(
        titleSpacing: 16,
        backgroundColor: scheme.surface,
        surfaceTintColor: Colors.transparent,
        title: Row(
          children: [
            Container(
              width: 34,
              height: 34,
              decoration: BoxDecoration(
                color: scheme.primary,
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(Icons.flight_takeoff, color: scheme.onPrimary, size: 20),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(widget.meta.name, style: text.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                  // Said once here rather than on every card, which is what
                  // `/api/meta` advertises it for.
                  Text(
                    'Flutter · ${provenance['label'] ?? 'Sample data'}',
                    style: text.labelSmall?.copyWith(color: scheme.onSurfaceVariant),
                  ),
                ],
              ),
            ),
          ],
        ),
        actions: [
          if (hasTrip)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: IconButton(
                tooltip: 'Your trip',
                onPressed: _openTrip,
                icon: Badge(
                  isLabelVisible: _panelChanged,
                  smallSize: 9,
                  child: const Icon(Icons.luggage_outlined),
                ),
              ),
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: _parts.isEmpty
                ? _Empty(
                    openers: widget.meta.openers,
                    onPick: (opener) => _send(message: opener),
                  )
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(14, 16, 14, 16),
                    itemCount: _parts.length,
                    itemBuilder: (context, index) => _part(_parts[index]),
                  ),
          ),
          if (_busy) const LinearProgressIndicator(minHeight: 2),
          if (hasTrip) _TripBar(changed: _panelChanged, onOpen: _openTrip),
          _Composer(
            controller: _composer,
            enabled: !_busy,
            // What to type next depends on where the conversation is: a
            // destination to begin with, then anything at all, including
            // changes to a trip that already has things on it.
            hint: _busy
                ? 'Working…'
                : _parts.isEmpty
                    ? 'Where are you going?'
                    : hasTrip
                        ? 'Ask anything, or change your trip'
                        : 'Reply, or ask for something else',
            onSend: (text) => _send(message: text),
          ),
        ],
      ),
    );
  }

  Widget _part(Part part) {
    final scheme = Theme.of(context).colorScheme;
    return switch (part) {
      SaidByYou(:final text) => Align(
          alignment: Alignment.centerRight,
          child: Container(
            margin: const EdgeInsets.only(bottom: 12, left: 56),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: scheme.primary,
              borderRadius: const BorderRadius.only(
                topLeft: Radius.circular(18),
                topRight: Radius.circular(18),
                bottomLeft: Radius.circular(18),
                bottomRight: Radius.circular(6),
              ),
            ),
            child: Text(text, style: TextStyle(color: scheme.onPrimary)),
          ),
        ),
      SaidByAgent(:final text) => Padding(
          padding: const EdgeInsets.only(bottom: 12, right: 24),
          child: Text(text, style: Theme.of(context).textTheme.bodyLarge),
        ),
      Drawn(:final surfaceId) => _drawn(surfaceId),
      Failed(:final message) => Container(
          margin: const EdgeInsets.only(bottom: 12),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: scheme.errorContainer,
            borderRadius: BorderRadius.circular(12),
          ),
          child: Text(message, style: TextStyle(color: scheme.onErrorContainer)),
        ),
    };
  }

  Widget _drawn(String surfaceId) {
    final surface = _processor.model.getSurface(surfaceId);
    if (surface == null) return const SizedBox.shrink();
    final scheme = Theme.of(context).colorScheme;

    final spent = surfaceId != _liveSurface;
    final card = Container(
      margin: const EdgeInsets.only(bottom: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: scheme.surface,
        border: Border.all(color: scheme.outlineVariant.withValues(alpha: 0.6)),
        borderRadius: BorderRadius.circular(18),
      ),
      child: A2uiSurface(surface: surface),
    );

    if (!spent) return card;

    // Greyed *and* inert. The greying matters on its own: a control that looks
    // live and does nothing is worse than one that looks finished.
    return Opacity(
      opacity: 0.55,
      child: IgnorePointer(child: card),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.openers, required this.onPick});

  final List<String> openers;
  final void Function(String) onPick;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 64,
              height: 64,
              decoration: BoxDecoration(
                color: scheme.primaryContainer,
                borderRadius: BorderRadius.circular(20),
              ),
              child: Icon(Icons.travel_explore, size: 32, color: scheme.onPrimaryContainer),
            ),
            const SizedBox(height: 16),
            Text('Where to?', style: text.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 8),
            Text(
              'Describe a trip and the agent answers with flights, stays and plans you can tap.',
              textAlign: TextAlign.center,
              style: text.bodyMedium?.copyWith(color: scheme.onSurfaceVariant),
            ),
            const SizedBox(height: 20),
            // The server's suggestions, one tap each: a tap is the same as
            // typing it and pressing send.
            for (final opener in openers)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: SizedBox(
                  width: double.infinity,
                  child: OutlinedButton(
                    onPressed: () => onPick(opener),
                    style: OutlinedButton.styleFrom(
                      alignment: Alignment.centerLeft,
                      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                      side: BorderSide(color: scheme.outlineVariant),
                    ),
                    child: Text(opener, style: text.bodyMedium),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// The cart: a bar that says there is a trip, and opens it.
///
/// Knows nothing about what is in it — no airline, no total — because what a
/// trip contains is the agent's to draw. It knows only that the panel exists
/// and whether it changed since it was last looked at.
class _TripBar extends StatelessWidget {
  const _TripBar({required this.changed, required this.onOpen});

  final bool changed;
  final VoidCallback onOpen;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 0),
      child: Material(
        color: scheme.inverseSurface,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          borderRadius: BorderRadius.circular(16),
          onTap: onOpen,
          child: Semantics(
            button: true,
            label: 'Your trip',
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
              child: Row(
                children: [
                  Badge(
                    isLabelVisible: changed,
                    smallSize: 9,
                    child: Icon(Icons.luggage_outlined, color: scheme.onInverseSurface),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(
                          'Your trip',
                          style: text.titleSmall?.copyWith(
                            color: scheme.onInverseSurface,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        Text(
                          changed ? 'Updated — tap to review' : 'Tap to review what you have chosen',
                          style: text.labelSmall?.copyWith(
                            color: scheme.onInverseSurface.withValues(alpha: 0.75),
                          ),
                        ),
                      ],
                    ),
                  ),
                  Icon(Icons.keyboard_arrow_up, color: scheme.onInverseSurface),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.enabled,
    required this.hint,
    required this.onSend,
  });

  final TextEditingController controller;
  final bool enabled;
  final String hint;
  final void Function(String) onSend;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                enabled: enabled,
                textInputAction: TextInputAction.send,
                onSubmitted: enabled ? onSend : null,
                decoration: InputDecoration(
                  hintText: hint,
                  filled: true,
                  fillColor: scheme.surfaceContainerHigh,
                  border: OutlineInputBorder(
                    borderRadius: BorderRadius.circular(24),
                    borderSide: BorderSide.none,
                  ),
                  contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
                  isDense: true,
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              tooltip: 'Send',
              onPressed: enabled ? () => onSend(controller.text) : null,
              icon: const Icon(Icons.arrow_upward),
            ),
          ],
        ),
      ),
    );
  }
}
