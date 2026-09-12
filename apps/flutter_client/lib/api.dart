// Talking to the server. The same endpoints the React client uses, because
// there is one server and it does not know which client is asking.
//
// A turn arrives as server-sent events. The events are not a Flutter protocol
// or a React protocol — they are the agent's own — so this file is a reader and
// not a translator, which is the whole reason a second client was worth
// building: if it had needed a translator, the first client's shape would have
// leaked into the server.

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// What the server says about itself, so nothing is compiled into the client.
class ServerMeta {
  ServerMeta(this.raw);

  final Map<String, dynamic> raw;

  String get name => raw['name'] as String? ?? 'Travel A2UI';
  String get defaultModel => raw['defaultModel'] as String? ?? '';
  String get defaultSkill => raw['defaultSkill'] as String? ?? '';
  bool get keyProvided => raw['keyProvided'] == true;

  /// Where the numbers came from, said once in the chrome rather than on every
  /// card.
  Map<String, dynamic> get provenance =>
      (raw['provenance'] as Map?)?.cast<String, dynamic>() ?? const {};

  List<Map<String, dynamic>> get backends => [
        for (final entry in (raw['backends'] as List? ?? const []))
          if (entry is Map) entry.cast<String, dynamic>(),
      ];
}

/// One event from a turn, as the agent emitted it.
class TurnEvent {
  TurnEvent(this.raw);

  final Map<String, dynamic> raw;

  String get type => raw['type'] as String? ?? '';
  String get delta => raw['delta'] as String? ?? '';
  String get surfaceId => raw['surfaceId'] as String? ?? '';

  List<Map<String, dynamic>> get messages => [
        for (final message in (raw['messages'] as List? ?? const []))
          if (message is Map) message.cast<String, dynamic>(),
      ];
}

/// Today, in the traveller's own calendar, as `YYYY-MM-DD`.
///
/// `DateTime.now()` is already local; the only trick is not letting
/// `toIso8601String` hand back a UTC instant, which is exactly the confusion
/// this is here to prevent on the server.
String _localToday() {
  final now = DateTime.now();
  return '${now.year.toString().padLeft(4, '0')}-'
      '${now.month.toString().padLeft(2, '0')}-'
      '${now.day.toString().padLeft(2, '0')}';
}

class TravelApi {
  TravelApi({required this.origin, this.apiKey = ''});

  /// Empty means same-origin, which is the deployed case: one service serves
  /// the client and the API, so there is no base URL to configure and no
  /// cross-origin request to allow.
  final String origin;
  String apiKey;

  Uri _url(String path) => Uri.parse('$origin$path');

  Future<ServerMeta> meta() async {
    final response = await http.get(_url('/api/meta'));
    return ServerMeta(jsonDecode(response.body) as Map<String, dynamic>);
  }

  Future<Map<String, dynamic>> catalog() async {
    final response = await http.get(_url('/api/catalog'));
    return jsonDecode(response.body) as Map<String, dynamic>;
  }

  /// One turn, streamed.
  ///
  /// `client.send` with a streamed response rather than `post`, because the
  /// point of the whole design is that a surface paints while the model is
  /// still writing it. Reading the body to completion first would work, render
  /// correctly, and take exactly as long as the slowest turn — which is the
  /// behaviour this replaces.
  Stream<TurnEvent> chat({
    String message = '',
    Map<String, dynamic>? action,
    String? sessionId,
    Map<String, dynamic>? resume,
    String surface = 'inline',
    String surfaceId = 'inline-1',
    String? model,
    String? skill,
  }) async* {
    final request = http.Request('POST', _url('/api/chat'))
      ..headers['content-type'] = 'application/json'
      ..headers['accept'] = 'text/event-stream';
    if (apiKey.isNotEmpty) request.headers['x-goog-api-key'] = apiKey;
    request.body = jsonEncode({
      if (message.isNotEmpty) 'message': message,
      if (action != null) 'action': action,
      if (sessionId != null) 'sessionId': sessionId,
      // The last turn's receipt, handed back unread. The server keeps its own
      // copy, but only on the instance that answered — and the next turn may
      // land on another one, which has never heard of this conversation.
      if (resume != null) 'resume': resume,
      'surface': surface,
      'surfaceId': surfaceId,
      if (model != null) 'model': model,
      if (skill != null) 'skill': skill,
      // What day it is here. The server runs in UTC and would otherwise plan
      // "tomorrow" against its own calendar rather than the traveller's.
      'client': {'today': _localToday()},
    });

    final response = await http.Client().send(request);

    if (response.statusCode >= 400) {
      final body = await response.stream.bytesToString();
      String detail = body;
      try {
        detail = (jsonDecode(body) as Map)['detail']?.toString() ?? body;
      } on FormatException {
        // The body was not JSON; the raw text is the best message there is.
      }
      yield TurnEvent({'type': 'error', 'message': detail, 'retryable': false});
      return;
    }

    // SSE frames are separated by a blank line, and a frame can arrive split
    // across chunks — so the buffer is the whole of the parsing.
    var buffer = '';
    await for (final chunk in response.stream.transform(utf8.decoder)) {
      buffer += chunk;
      while (true) {
        final boundary = buffer.indexOf('\n\n');
        if (boundary == -1) break;
        final frame = buffer.substring(0, boundary);
        buffer = buffer.substring(boundary + 2);
        for (final line in frame.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          final payload = line.substring(6);
          try {
            yield TurnEvent(jsonDecode(payload) as Map<String, dynamic>);
          } on FormatException {
            // A frame we cannot read is skipped rather than ending the turn:
            // the surfaces already on screen are still correct.
          }
        }
      }
    }
  }
}
