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
import 'package:flutter/material.dart';

import 'api.dart';
import 'catalog.dart';
import 'surface.dart';

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
  final Catalog<FlutterComponent> catalog;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  late final MessageProcessor<FlutterComponent> _processor;
  final _parts = <Part>[];
  final _composer = TextEditingController();
  final _scroll = ScrollController();

  String? _sessionId;
  bool _busy = false;
  int _surfaceCounter = 0;

  /// The surface a press is still allowed to come from.
  String? _liveSurface;

  @override
  void initState() {
    super.initState();
    _processor = MessageProcessor<FlutterComponent>(
      catalogs: [widget.catalog],
      onAction: _onAction,
    );
  }

  @override
  void dispose() {
    _composer.dispose();
    _scroll.dispose();
    super.dispose();
  }

  /// Somebody pressed something. That is their turn.
  ///
  /// Sent as the action the renderer produced, with the surface's data model
  /// attached: the context is what the button declared it was sending, and the
  /// data model is everything else they set that no binding named. A client
  /// that omits the second still works, which is the test of whether this is a
  /// protocol or an arrangement.
  void _onAction(A2uiClientAction action) {
    if (_busy) return;
    if (action.surfaceId != _liveSurface) return;

    final surface = _processor.groupModel.getSurface(action.surfaceId);
    _send(
      action: {
        'name': action.name,
        'surfaceId': action.surfaceId,
        'sourceComponentId': action.sourceComponentId,
        'timestamp': action.timestamp.toIso8601String(),
        'context': action.context,
        if (surface != null) 'dataModel': surface.dataModel.get('/'),
      },
    );
  }

  Future<void> _send({String message = '', Map<String, dynamic>? action}) async {
    if (_busy) return;
    if (message.isEmpty && action == null) return;

    // A new inline surface per turn: two different questions get two different
    // cards, and the previous one stays as the record of what was asked.
    _surfaceCounter += 1;
    final surfaceId = 'inline-$_surfaceCounter';

    setState(() {
      _busy = true;
      if (message.isNotEmpty) _parts.add(SaidByYou(message));
      _liveSurface = surfaceId;
    });
    _composer.clear();
    _toBottom();

    SaidByAgent? speaking;

    try {
      final stream = widget.api.chat(
        message: message,
        action: action,
        sessionId: _sessionId,
        surfaceId: surfaceId,
      );

      await for (final event in stream) {
        switch (event.type) {
          case 'session':
            _sessionId = event.raw['sessionId'] as String?;

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
    try {
      _processor.processMessages([
        for (final message in event.messages) A2uiMessage.fromJson(_readable(message)),
      ]);
      _seed(event.messages);
    } on A2uiStateError {
      // A surface that already exists, or components for one that does not.
      // Both happen while streaming and neither should end a turn: the surface
      // on screen is still the right one.
      return;
    } on A2uiValidationError catch (error) {
      setState(() => _parts.add(Failed('That surface could not be read: ${error.message}')));
      return;
    }

    final existing = _parts.whereType<Drawn>().any((part) => part.surfaceId == event.surfaceId);
    if (!existing && _processor.groupModel.getSurface(event.surfaceId) != null) {
      setState(() => _parts.add(Drawn(event.surfaceId)));
      _toBottom();
    }
  }

  /// Two adaptations between this server and this build of `a2ui_core`.
  ///
  /// **The version string.** The core accepts `v0.9` and the server emits
  /// `v0.9.1` — the spec revision the catalog is written against. The core
  /// rejects anything else outright, so without this every message raises and
  /// nothing renders at all. Normalised here rather than on the wire: the
  /// React client and every MCP payload already carry `v0.9.1`, and changing
  /// what the server emits to suit one client's dependency is the wrong way
  /// round. Delete this when the core accepts the patch revision.
  Map<String, dynamic> _readable(Map<String, dynamic> message) {
    final version = message['version'];
    if (version is String && version.startsWith('v0.9') && version != 'v0.9') {
      return {...message, 'version': 'v0.9'};
    }
    return message;
  }

  /// **The seeded data model.** The server fills `createSurface.dataModel` with
  /// the trip and the plan, so a control opens showing what is already decided
  /// and a panel has its checklist before anything is decided. This build of
  /// the core's `CreateSurfaceMessage` has no such field and drops it — so the
  /// seed is applied here, after the surface exists.
  ///
  /// Without this the Flutter client renders every control empty while the
  /// React client renders them pre-filled, from identical messages. Nothing
  /// would report it.
  void _seed(List<Map<String, dynamic>> messages) {
    for (final message in messages) {
      final created = message['createSurface'];
      if (created is! Map) continue;
      final seed = created['dataModel'];
      if (seed is! Map) continue;
      final surface = _processor.groupModel.getSurface(created['surfaceId'] as String);
      if (surface == null) continue;
      seed.forEach((key, value) => surface.dataModel.set('/$key', value));
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

  @override
  Widget build(BuildContext context) {
    final provenance = widget.meta.provenance;
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.meta.name),
        bottom: PreferredSize(
          preferredSize: const Size.fromHeight(22),
          child: Padding(
            padding: const EdgeInsets.only(left: 16, bottom: 6),
            child: Align(
              alignment: Alignment.centerLeft,
              // Said once here rather than on every card, which is what
              // `/api/meta` advertises it for.
              child: Text(
                'Flutter renderer · ${provenance['label'] ?? 'Sample data'}',
                style: Theme.of(context).textTheme.bodySmall,
              ),
            ),
          ),
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: _parts.isEmpty
                ? const _Empty()
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.all(16),
                    itemCount: _parts.length,
                    itemBuilder: (context, index) => _part(_parts[index]),
                  ),
          ),
          if (_busy) const LinearProgressIndicator(minHeight: 2),
          _Composer(controller: _composer, enabled: !_busy, onSend: (text) => _send(message: text)),
        ],
      ),
    );
  }

  Widget _part(Part part) {
    return switch (part) {
      SaidByYou(:final text) => Align(
          alignment: Alignment.centerRight,
          child: Container(
            margin: const EdgeInsets.only(bottom: 12, left: 48),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: Theme.of(context).colorScheme.primaryContainer,
              borderRadius: BorderRadius.circular(14),
            ),
            child: Text(text),
          ),
        ),
      SaidByAgent(:final text) => Padding(
          padding: const EdgeInsets.only(bottom: 12, right: 32),
          child: Text(text, style: Theme.of(context).textTheme.bodyLarge),
        ),
      Drawn(:final surfaceId) => _drawn(surfaceId),
      Failed(:final message) => Container(
          margin: const EdgeInsets.only(bottom: 12),
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: Theme.of(context).colorScheme.errorContainer,
            borderRadius: BorderRadius.circular(10),
          ),
          child: Text(message),
        ),
    };
  }

  Widget _drawn(String surfaceId) {
    final surface = _processor.groupModel.getSurface(surfaceId);
    if (surface == null) return const SizedBox.shrink();

    final spent = surfaceId != _liveSurface;
    final card = Container(
      margin: const EdgeInsets.only(bottom: 16, right: 16),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
        borderRadius: BorderRadius.circular(14),
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
  const _Empty();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Describe a trip.', style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 8),
            Text(
              'Try: "I want to go from San Francisco to London and back, for two of us."',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ],
        ),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({required this.controller, required this.enabled, required this.onSend});

  final TextEditingController controller;
  final bool enabled;
  final void Function(String) onSend;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            Expanded(
              child: TextField(
                controller: controller,
                enabled: enabled,
                textInputAction: TextInputAction.send,
                onSubmitted: enabled ? onSend : null,
                decoration: const InputDecoration(
                  hintText: 'Where are you going?',
                  border: OutlineInputBorder(),
                  isDense: true,
                ),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              onPressed: enabled ? () => onSend(controller.text) : null,
              icon: const Icon(Icons.arrow_upward),
            ),
          ],
        ),
      ),
    );
  }
}
