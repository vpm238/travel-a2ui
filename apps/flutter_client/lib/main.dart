// The Flutter client: the same agent, drawn by a different toolkit.
//
// It exists to test one claim. If the interface really is a protocol rather
// than a feature of one app, then a second client should be a renderer and
// nothing else — no travel logic, no idea what a trip is, no private agreement
// with the server about what a button means. That is the whole of what this is.
//
// What it does *not* contain is the interesting part: no list of trip fields,
// no code that decides when the panel needs redrawing, no sentence composed to
// describe what somebody pressed. All of that is on the server, where it is
// shared with the React client and with Claude.

import 'package:flutter/material.dart';

import 'api.dart';
import 'catalog.dart';
import 'chat.dart';

void main() => runApp(const TravelApp());

class TravelApp extends StatelessWidget {
  const TravelApp({super.key});

  @override
  Widget build(BuildContext context) {
    final seed = const Color(0xFF1F3F9E);
    return MaterialApp(
      title: 'Travel A2UI · Flutter',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed),
        useMaterial3: true,
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed, brightness: Brightness.dark),
        useMaterial3: true,
      ),
      home: const _Boot(),
    );
  }
}

/// Fetches what the server says about itself, then hands over to the chat.
///
/// Nothing is drawn before the catalog arrives, because there is nothing this
/// client can draw without it. That is not a loading state so much as an honest
/// statement of where the vocabulary lives.
class _Boot extends StatefulWidget {
  const _Boot();

  @override
  State<_Boot> createState() => _BootState();
}

class _BootState extends State<_Boot> {
  late final TravelApi _api = TravelApi(origin: '');
  Object? _error;
  ServerMeta? _meta;
  Map<String, dynamic>? _catalogJson;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final meta = await _api.meta();
      final catalogJson = await _api.catalog();
      if (!mounted) return;
      setState(() {
        _meta = meta;
        _catalogJson = catalogJson;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return Scaffold(
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('Could not reach the server.',
                    style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: 8),
                Text('$_error', textAlign: TextAlign.center),
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: () {
                    setState(() => _error = null);
                    _load();
                  },
                  child: const Text('Try again'),
                ),
              ],
            ),
          ),
        ),
      );
    }

    final meta = _meta;
    final catalogJson = _catalogJson;
    if (meta == null || catalogJson == null) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }

    return ChatScreen(
      api: _api,
      meta: meta,
      catalog: buildCatalog(catalogJson),
    );
  }
}
