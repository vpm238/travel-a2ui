// The catalog's functions, implemented for Flutter.
//
// These run *in the renderer*, against the live data model, which is the whole
// reason they exist. A label bound to `calcNights` recomputes the instant a date
// picker moves — no turn, no wait, no tokens. The alternative is the model
// writing "3 nights" as literal text, which is correct in the screenshot and a
// lie the moment the traveller drags something, and which nothing downstream
// ever notices because a string is a string.
//
// Each one is driven from `catalog.json` on the React side by a test that walks
// the declared functions and fails when one is declared but not implemented.
// The same test is here, in `test/functions_test.dart`, and for the same
// reason: `formatString` once shipped without implementing its own spec, and
// the tests agreed with it because they had been written from the code.

import 'package:a2ui_core/a2ui_core.dart';
import 'package:intl/intl.dart';
import 'package:json_schema_builder/json_schema_builder.dart';

/// Resolves an argument that may be a literal or a signal.
Object? _value(Object? raw) => raw is ReadonlySignal ? raw.value : raw;

String _string(Map<String, dynamic> args, String key, [String fallback = '']) {
  final value = _value(args[key]);
  return value == null ? fallback : value.toString();
}

num? _number(Map<String, dynamic> args, String key) {
  final value = _value(args[key]);
  if (value is num) return value;
  if (value is String) return num.tryParse(value.replaceAll(RegExp(r'[^0-9.\-]'), ''));
  return null;
}

abstract class _Fn extends FunctionImplementation {
  @override
  Schema get argumentSchema => Schema.object(properties: const {});
}

/// Nights slept, not days spanned: 12th to 15th is three.
///
/// Zero when either end is missing or the range runs backwards, so a half-
/// filled form shows a zero rather than nonsense — and so a picker mid-drag
/// never briefly reads "-4 nights".
class CalcNights extends _Fn {
  @override
  String get name => 'calcNights';

  @override
  A2uiReturnType get returnType => A2uiReturnType.number;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final start = DateTime.tryParse(_string(args, 'start'));
    final end = DateTime.tryParse(_string(args, 'end'));
    if (start == null || end == null) return 0;
    final nights = end.difference(start).inDays;
    return nights > 0 ? nights : 0;
  }
}

/// `${…}` placeholders, filled from the resolved arguments.
///
/// The spec this once failed to implement: a template may reference any other
/// argument by name, and may contain a nested call whose result has already
/// been resolved by the time it arrives here.
class FormatString extends _Fn {
  @override
  String get name => 'formatString';

  @override
  A2uiReturnType get returnType => A2uiReturnType.string;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final template = _string(args, 'value');
    return template.replaceAllMapped(RegExp(r'\$\{([^}]*)\}'), (match) {
      final key = match.group(1)!.trim();
      final replacement = _value(args[key]);
      return replacement?.toString() ?? '';
    });
  }
}

class FormatNumber extends _Fn {
  @override
  String get name => 'formatNumber';

  @override
  A2uiReturnType get returnType => A2uiReturnType.string;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final value = _number(args, 'value');
    if (value == null) return '';
    final decimals = _number(args, 'decimals')?.toInt();
    return decimals == null
        ? NumberFormat.decimalPattern('en_US').format(value)
        : value.toStringAsFixed(decimals);
  }
}

class FormatCurrency extends _Fn {
  @override
  String get name => 'formatCurrency';

  @override
  A2uiReturnType get returnType => A2uiReturnType.string;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final value = _number(args, 'value');
    if (value == null) return '';
    final currency = _string(args, 'currency', 'USD');
    // Whole units: a fare is $352, not $352.00. The fixtures round before they
    // ever reach a surface, so showing cents here would show two zeroes.
    return NumberFormat.simpleCurrency(locale: 'en_US', name: currency, decimalDigits: 0)
        .format(value);
  }
}

class FormatDate extends _Fn {
  @override
  String get name => 'formatDate';

  @override
  A2uiReturnType get returnType => A2uiReturnType.string;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final parsed = DateTime.tryParse(_string(args, 'value'));
    if (parsed == null) return '';
    final pattern = _string(args, 'format', 'd MMM');
    return DateFormat(pattern, 'en_US').format(parsed);
  }
}

class Pluralize extends _Fn {
  @override
  String get name => 'pluralize';

  @override
  A2uiReturnType get returnType => A2uiReturnType.string;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final count = _number(args, 'value')?.toInt() ?? 0;
    return count == 1 ? _string(args, 'one') : _string(args, 'other');
  }
}

class And extends _Fn {
  @override
  String get name => 'and';

  @override
  A2uiReturnType get returnType => A2uiReturnType.boolean;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final values = _value(args['values']);
    if (values is! List) return false;
    return values.every((item) => _value(item) == true);
  }
}

class Or extends _Fn {
  @override
  String get name => 'or';

  @override
  A2uiReturnType get returnType => A2uiReturnType.boolean;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final values = _value(args['values']);
    if (values is! List) return false;
    return values.any((item) => _value(item) == true);
  }
}

class Not extends _Fn {
  @override
  String get name => 'not';

  @override
  A2uiReturnType get returnType => A2uiReturnType.boolean;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) =>
      _value(args['value']) != true;
}

/// The validators. They answer "is this acceptable", and a missing value is
/// only unacceptable to `required` — everything else passes on empty, so a form
/// does not shout at somebody who has not typed yet.
class Required extends _Fn {
  @override
  String get name => 'required';

  @override
  A2uiReturnType get returnType => A2uiReturnType.boolean;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final value = _value(args['value']);
    if (value == null) return false;
    if (value is String) return value.trim().isNotEmpty;
    if (value is Iterable) return value.isNotEmpty;
    return true;
  }
}

class RegexCheck extends _Fn {
  @override
  String get name => 'regex';

  @override
  A2uiReturnType get returnType => A2uiReturnType.boolean;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final value = _string(args, 'value');
    if (value.isEmpty) return true;
    final pattern = _string(args, 'pattern');
    if (pattern.isEmpty) return true;
    try {
      return RegExp(pattern).hasMatch(value);
    } on FormatException {
      // A pattern the model wrote wrong should not make the field unfillable.
      return true;
    }
  }
}

class LengthCheck extends _Fn {
  @override
  String get name => 'length';

  @override
  A2uiReturnType get returnType => A2uiReturnType.boolean;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final value = _string(args, 'value');
    if (value.isEmpty) return true;
    final min = _number(args, 'min')?.toInt();
    final max = _number(args, 'max')?.toInt();
    if (min != null && value.length < min) return false;
    if (max != null && value.length > max) return false;
    return true;
  }
}

class NumericCheck extends _Fn {
  @override
  String get name => 'numeric';

  @override
  A2uiReturnType get returnType => A2uiReturnType.boolean;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final raw = _value(args['value']);
    if (raw == null || (raw is String && raw.isEmpty)) return true;
    final value = raw is num ? raw : num.tryParse(raw.toString());
    if (value == null) return false;
    final min = _number(args, 'min');
    final max = _number(args, 'max');
    if (min != null && value < min) return false;
    if (max != null && value > max) return false;
    return true;
  }
}

class EmailCheck extends _Fn {
  @override
  String get name => 'email';

  @override
  A2uiReturnType get returnType => A2uiReturnType.boolean;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final value = _string(args, 'value');
    if (value.isEmpty) return true;
    return RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(value);
  }
}

/// Declared by the catalog and deliberately inert on the web client.
///
/// A surface that asks the host to open a URL is asking for a navigation the
/// traveller did not initiate, and in a browser tab that is a popup. It is
/// implemented so the function is not *missing* — a missing function is a
/// binding that resolves to nothing, which renders as a blank — and does
/// nothing, which is the honest behaviour rather than a silent hole.
class OpenUrl extends _Fn {
  @override
  String get name => 'openUrl';

  @override
  A2uiReturnType get returnType => A2uiReturnType.void_;

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) =>
      null;
}

/// Every function the catalog declares.
List<FunctionImplementation> catalogFunctions() => [
      CalcNights(),
      FormatString(),
      FormatNumber(),
      FormatCurrency(),
      FormatDate(),
      Pluralize(),
      And(),
      Or(),
      Not(),
      Required(),
      RegexCheck(),
      LengthCheck(),
      NumericCheck(),
      EmailCheck(),
      OpenUrl(),
    ];
