// The travel catalog's two functions of its own.
//
// Every other function a surface can call (formatString, formatCurrency,
// pluralize, the checks) is the A2UI basic catalog's, and `a2ui_core`
// implements those. These two are the travel catalog's additions, implemented
// here and in `renderers/react/src/functions.ts` to the same contract, which
// the catalog declares and the tests on both sides pin.
//
// They run in the renderer, against the live data model. A label bound to
// `calcNights` recomputes the instant a date picker moves, with no turn and no
// tokens, where a label the model wrote as "3 nights" would be wrong the moment
// the traveller dragged something.

import 'package:a2ui_core/a2ui_core.dart';

Object? _value(Object? raw) => raw is ReadonlySignal ? raw.value : raw;

String _text(Map<String, dynamic> args, String key) {
  final value = _value(args[key]);
  return value == null ? '' : '$value';
}

/// The calendar date at the start of an ISO string, ignoring any time or offset.
DateTime? _calendarDate(String value) {
  final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})').firstMatch(value);
  if (match == null) return null;
  return DateTime.utc(
    int.parse(match.group(1)!),
    int.parse(match.group(2)!),
    int.parse(match.group(3)!),
  );
}

/// A function the travel catalog declares, with the signature it declares.
abstract class _Declared extends FunctionImplementation {
  _Declared(FunctionApi api)
      : super(
          name: api.name,
          argumentSchema: api.argumentSchema,
          returnType: api.returnType,
          description: api.description,
          allowedCallers: api.declaredAllowedCallers,
          requiresUserActivation: api.declaredRequiresUserActivation,
          definition: api.definition,
        );
}

/// Nights slept between two calendar dates: 12 Apr to 15 Apr is three.
///
/// Counted on calendar dates in UTC, so a daylight-saving change inside the
/// range cannot make a night 23 hours long and round it away. A half-filled or
/// inverted range is zero nights.
class CalcNights extends _Declared {
  CalcNights(super.api);

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final start = _calendarDate(_text(args, 'start'));
    final end = _calendarDate(_text(args, 'end'));
    if (start == null || end == null) return 0;
    final nights = end.difference(start).inDays;
    return nights > 0 ? nights : 0;
  }
}

/// Whether two values are the same, compared as text, for marking the row a
/// trip chose. Nothing chosen yet is never a match.
class Equals extends _Declared {
  Equals(super.api);

  @override
  Object? execute(Map<String, dynamic> args, DataContext context, [CancellationSignal? signal]) {
    final a = _value(args['a']);
    final b = _value(args['b']);
    if (a == null || b == null || '$a'.isEmpty) return false;
    return '$a' == '$b';
  }
}

/// The travel catalog's own functions, built against its declarations.
final Map<String, FunctionImplementation Function(FunctionApi)> travelFunctions = {
  'calcNights': CalcNights.new,
  'equals': Equals.new,
};
