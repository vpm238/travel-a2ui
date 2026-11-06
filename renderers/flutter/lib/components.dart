// The fourteen travel components, drawn in Flutter.
//
// Everything else a surface can hold — Text, Row, Column, List, Card, Button,
// the editors — is the A2UI SDK's own: `a2ui_flutter`'s basic catalog draws it,
// and `catalog.dart` puts the two together. What is left here is only what the
// basic catalog cannot know: what a flight, a hotel or a trip calendar looks
// like.
//
// Each builder receives properties the SDK has already resolved. Its binder has
// walked the schema, followed every binding into the data model, run every
// function call and wrapped each action, so nothing here reads a path or
// evaluates an expression.
//
// The one idea carried over from the React views is the pending state. A
// binding whose path does not resolve yet is *pending*; a path resolving to an
// empty string is *empty*. That is what lets a surface paint its layout the
// moment a search starts and fill in when the rows land.

import 'dart:async';

import 'package:a2ui_core/a2ui_core.dart';
import 'package:a2ui_flutter/a2ui_flutter.dart';
import 'package:flutter/material.dart';

/// The SDK's resolved properties, read the way the travel views read them.
///
/// A view over `ComponentProps`, not a second binder: every value here is one
/// the SDK resolved, and every write and action goes back through the SDK's own
/// `WritableBinding` and `NodeAction`.
class TravelProps {
  const TravelProps(this.props, this.buildChild);

  final ComponentProps props;
  final ChildWidgetBuilder buildChild;

  /// A property as plain JSON, with any binding inside it resolved.
  Object? operator [](String key) => _plain(props[key]);

  static Object? _plain(Object? value) {
    final unwrapped = ComponentProps.unwrap(value);
    if (unwrapped is List) return [for (final item in unwrapped) _plain(item)];
    if (unwrapped is Map) {
      return <String, Object?>{
        for (final entry in unwrapped.entries) '${entry.key}': _plain(entry.value),
      };
    }
    return unwrapped;
  }

  String? string(String key) => props.string(key);

  num? number(String key) {
    final value = props.value(key);
    if (value is num) return value;
    if (value is String) return num.tryParse(value);
    return null;
  }

  bool flag(String key) => props.value(key) == true;

  /// Bound to a path that has nothing at it yet.
  ///
  /// Only a property the component *has*: one it was never given is absent,
  /// not loading, and drawing a loading bar for it shimmers for ever — a trip
  /// panel's fare has no duration, and its card waited for one.
  bool pending(String key) => props.containsKey(key) && props.value(key) == null;

  /// Not given at all.
  bool absent(String key) => !props.containsKey(key);

  bool get hasAction => has('action');

  bool has(String key) => props.action(key) != null;

  void fire([String key = 'action']) => unawaited(props.action(key)?.call());

  /// Writes an edit back to the data model, through the SDK's binding.
  void write(String key, Object? value) => props.writable(key)?.set(value);

  List<Widget> children(String key) => [for (final node in props.children(key)) buildChild(node)];
}

/// A travel view, as `a2ui_flutter` calls it.
typedef TravelView = Widget Function(BuildContext context, TravelProps build);

/// `yyyy-MM-dd`: the calendar date the DateRangePicker contract binds.
String _calendarDate(DateTime day) =>
    '${day.year.toString().padLeft(4, '0')}-${day.month.toString().padLeft(2, '0')}-${day.day.toString().padLeft(2, '0')}';


/// A card the traveller can press.
///
/// `InkWell` alone registers a tap handler but does not claim to *be* a button,
/// and Flutter draws to a canvas — so on the web the card lands in the
/// accessibility tree as an anonymous group with no role and no way to
/// activate it. A screen-reader user can then hear four flights and choose
/// none of them, which is a broken surface however good it looks.
///
/// `button: true` is what makes it a real control, and the flag belongs here
/// rather than on each card so that the next tappable component gets it by
/// construction.
Widget _tappable({required VoidCallback? onTap, required Widget child}) {
  return Semantics(
    button: onTap != null,
    enabled: onTap != null,
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: child,
    ),
  );
}

/// A field that is still loading, drawn as a shimmering bar.
class _Pending extends StatelessWidget {
  const _Pending({this.width = 64});

  final double width;
  static const double height = 12;

  @override
  Widget build(BuildContext context) {
    final base = Theme.of(context).colorScheme.onSurface.withValues(alpha: 0.08);
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(color: base, borderRadius: BorderRadius.circular(4)),
    );
  }
}

/// Text, or a pending bar when what it is bound to has not arrived.
Widget _bound(TravelProps build, String key, TextStyle? style, {double width = 64, bool waiting = true}) {
  if (build.absent(key)) return const SizedBox.shrink();
  // `waiting` is whether the card as a whole is still on its way. A detail
  // missing from a card that has arrived — a trip panel's fare has no
  // duration — is not loading, and a bar there would shimmer for ever.
  if (build.pending(key)) return waiting ? _Pending(width: width) : const SizedBox.shrink();
  return Text(build.string(key) ?? '', style: style);
}

// ---------------------------------------------------------------------------
// Layout and basics
// ---------------------------------------------------------------------------

/// A steady hue per airline, so the same carrier wears the same colour.
Color _hueFor(String name, Brightness brightness) {
  var seed = 0;
  for (final unit in name.codeUnits) {
    seed = (seed * 31 + unit) & 0x7fffffff;
  }
  return HSLColor.fromAHSL(
    1,
    (seed % 360).toDouble(),
    0.45,
    brightness == Brightness.dark ? 0.62 : 0.42,
  ).toColor();
}

/// Up to two letters for a carrier's badge: "TAP Air Portugal" → "TP".
String _initials(String name) {
  final words = name.split(RegExp(r'\s+')).where((word) => word.isNotEmpty).toList();
  if (words.isEmpty) return '';
  if (words.length == 1) return words.first.substring(0, words.first.length.clamp(0, 2)).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}

Widget _flightOption(BuildContext context, TravelProps build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  final badge = build.string('badge');
  final total = build.string('total');
  final airline = build.string('airline') ?? '';
  final chosen = build.flag('selected');
  final hue = _hueFor(airline, Theme.of(context).brightness);
  final muted = text.labelSmall?.copyWith(color: scheme.onSurfaceVariant, letterSpacing: 0.4);
  // Still on its way: the facts every fare row has are not here yet.
  final waiting = build.pending('airline') || build.pending('price');

  // A time, and the airport under it.
  Widget end(String time, String place, CrossAxisAlignment side) => Column(
        crossAxisAlignment: side,
        mainAxisSize: MainAxisSize.min,
        children: [
          _bound(build, time, text.titleLarge?.copyWith(fontWeight: FontWeight.w800), width: 52),
          const SizedBox(height: 2),
          _bound(build, place, muted, width: 30),
        ],
      );

  return _tappable(
    onTap: build.hasAction ? build.fire : null,
    child: AnimatedContainer(
      duration: const Duration(milliseconds: 160),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: chosen ? scheme.primaryContainer.withValues(alpha: 0.35) : scheme.surface,
        border: Border.all(
          color: chosen ? scheme.primary : scheme.outlineVariant.withValues(alpha: 0.7),
          width: chosen ? 2 : 1,
        ),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              // The carrier's badge: initials on its own colour.
              Container(
                width: 38,
                height: 38,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: hue.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(11),
                ),
                child: Text(
                  _initials(airline),
                  style: text.labelLarge?.copyWith(color: hue, fontWeight: FontWeight.w800),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _bound(build, 'airline', text.titleSmall?.copyWith(fontWeight: FontWeight.w700), width: 96),
                    _bound(build, 'flightNumber', muted, width: 44, waiting: waiting),
                  ],
                ),
              ),
              Column(
                crossAxisAlignment: CrossAxisAlignment.end,
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (badge != null && badge.isNotEmpty)
                    Container(
                      margin: const EdgeInsets.only(bottom: 4),
                      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                      decoration: BoxDecoration(
                        color: scheme.tertiaryContainer,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        badge.toUpperCase(),
                        style: text.labelSmall?.copyWith(
                          color: scheme.onTertiaryContainer,
                          fontWeight: FontWeight.w700,
                          letterSpacing: 0.6,
                          fontSize: 10,
                        ),
                      ),
                    ),
                  _bound(build, 'price', text.titleLarge?.copyWith(fontWeight: FontWeight.w800), width: 56),
                  // What the whole party pays, when the leg carries more than
                  // one person: `price` is per traveller.
                  if (total != null && total.isNotEmpty)
                    Text(total, style: muted),
                ],
              ),
            ],
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              end('departTime', 'origin', CrossAxisAlignment.start),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _bound(build, 'duration', muted, width: 44, waiting: waiting),
                      const SizedBox(height: 4),
                      // The route: two airports and the line between them.
                      Row(
                        children: [
                          Icon(Icons.circle_outlined, size: 8, color: scheme.outline),
                          Expanded(child: Container(height: 1.4, color: scheme.outlineVariant)),
                          RotatedBox(quarterTurns: 1, child: Icon(Icons.flight, size: 14, color: scheme.outline)),
                          Expanded(child: Container(height: 1.4, color: scheme.outlineVariant)),
                          Icon(Icons.circle_outlined, size: 8, color: scheme.outline),
                        ],
                      ),
                      const SizedBox(height: 4),
                      _bound(build, 'stops', muted, width: 60, waiting: waiting),
                    ],
                  ),
                ),
              ),
              end('arriveTime', 'destination', CrossAxisAlignment.end),
            ],
          ),
        ],
      ),
    ),
  );
}

Widget _hotelCard(BuildContext context, TravelProps build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  final amenities = build['amenities'];

  return _tappable(
    onTap: build.hasAction ? build.fire : null,
    child: Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        border: Border.all(color: scheme.outlineVariant),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              Expanded(child: _bound(build, 'name', text.titleMedium, width: 120)),
              _bound(build, 'price', text.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                  width: 56),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            children: [
              _bound(build, 'neighborhood', text.bodySmall, width: 70),
              const SizedBox(width: 10),
              if (!build.pending('rating'))
                Text('★ ${build.string('rating')}', style: text.bodySmall),
            ],
          ),
          if (amenities is List && amenities.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final amenity in amenities)
                  Chip(
                    label: Text(amenity.toString(), style: text.labelSmall),
                    visualDensity: VisualDensity.compact,
                    materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                  ),
              ],
            ),
          ],
        ],
      ),
    ),
  );
}

Widget _statTile(BuildContext context, TravelProps build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  final tone = build.string('tone');
  final colour = switch (tone) {
    'accent' => scheme.primary,
    'positive' => scheme.tertiary,
    'critical' => scheme.error,
    'caution' => scheme.secondary,
    _ => scheme.onSurface,
  };
  return Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: scheme.surfaceContainerHighest,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(build.string('label') ?? '', style: text.labelMedium),
        const SizedBox(height: 4),
        _bound(build, 'value', text.headlineSmall?.copyWith(color: colour), width: 60),
        if (!build.pending('caption'))
          Text(build.string('caption') ?? '', style: text.bodySmall),
      ],
    ),
  );
}

Widget _progressMeter(BuildContext context, TravelProps build) {
  final text = Theme.of(context).textTheme;
  final value = build.number('value')?.toDouble() ?? 0;
  final total = build.number('total')?.toDouble() ?? 1;
  final tone = build.string('tone');
  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(build.string('label') ?? '', style: text.labelLarge),
      const SizedBox(height: 6),
      ClipRRect(
        borderRadius: BorderRadius.circular(999),
        child: LinearProgressIndicator(
          value: total <= 0 ? 0 : (value / total).clamp(0, 1).toDouble(),
          minHeight: 8,
          color: tone == 'critical' ? Theme.of(context).colorScheme.error : null,
        ),
      ),
      if (!build.pending('caption')) ...[
        const SizedBox(height: 4),
        Text(build.string('caption') ?? '', style: text.bodySmall),
      ],
    ],
  );
}

Widget _priceSummary(BuildContext context, TravelProps build) {
  final text = Theme.of(context).textTheme;
  final lines = build['lines'];
  return Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    mainAxisSize: MainAxisSize.min,
    children: [
      if (lines is List)
        for (final line in lines)
          if (line is Map)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                children: [
                  Expanded(child: Text(line['label']?.toString() ?? '', style: text.bodyMedium)),
                  if (line['note'] != null)
                    Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: Text(line['note'].toString(), style: text.bodySmall),
                    ),
                  Text(line['amount']?.toString() ?? '', style: text.bodyMedium),
                ],
              ),
            ),
      const Divider(),
      Row(
        children: [
          Expanded(
            child: Text(build.string('totalLabel') ?? 'Total', style: text.titleMedium),
          ),
          _bound(build, 'total', text.titleMedium?.copyWith(fontWeight: FontWeight.w700),
              width: 64),
        ],
      ),
      if (!build.pending('caption'))
        Text(build.string('caption') ?? '', style: text.bodySmall),
    ],
  );
}

Widget _itineraryDay(BuildContext context, TravelProps build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  return Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      border: Border.all(color: scheme.outlineVariant),
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          children: [
            Expanded(child: Text(build.string('title') ?? '', style: text.titleMedium)),
            if (!build.pending('date'))
              Text(build.string('date') ?? '', style: text.bodySmall),
          ],
        ),
        if (!build.pending('summary'))
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Text(build.string('summary') ?? '', style: text.bodySmall),
          ),
        const SizedBox(height: 8),
        ...build.children('activities'),
        if (build.has('onAdd'))
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(
              onPressed: () => build.fire('onAdd'),
              child: const Text('+ Add something else'),
            ),
          ),
      ],
    ),
  );
}

Widget _activityItem(BuildContext context, TravelProps build) {
  final text = Theme.of(context).textTheme;
  return Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 52,
          child: _bound(build, 'time', text.bodySmall, width: 40),
        ),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              _bound(build, 'title', text.bodyMedium, width: 110),
              if (!build.pending('note'))
                Text(build.string('note') ?? '', style: text.bodySmall),
            ],
          ),
        ),
        // Always visible here, unlike the web's hover-revealed control: there
        // is no hover on a phone, and an affordance a touch device cannot
        // reach is not an affordance.
        if (build.has('onRemove'))
          IconButton(
            icon: const Icon(Icons.close, size: 18),
            tooltip: 'Remove ${build.string('title') ?? 'this'}',
            visualDensity: VisualDensity.compact,
            onPressed: () => build.fire('onRemove'),
          ),
      ],
    ),
  );
}

Widget _weatherStrip(BuildContext context, TravelProps build) {
  final text = Theme.of(context).textTheme;
  final days = build['days'];
  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      if (!build.pending('place'))
        Text(build.string('place') ?? '', style: text.labelLarge),
      const SizedBox(height: 6),
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        child: Row(
          children: [
            if (days is List)
              for (final day in days)
                if (day is Map)
                  Padding(
                    padding: const EdgeInsets.only(right: 14),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(day['day']?.toString() ?? '', style: text.labelSmall),
                        Text(day['high']?.toString() ?? '', style: text.bodyMedium),
                        Text(day['low']?.toString() ?? '', style: text.bodySmall),
                      ],
                    ),
                  ),
          ],
        ),
      ),
      if (!build.pending('caption'))
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(build.string('caption') ?? '', style: text.bodySmall),
        ),
    ],
  );
}

/// A `GoogleMap`, in a client that cannot draw one.
///
/// The React renderer mounts the Maps JavaScript API's own `gmp-map-3d` and
/// shows a real map. This client has no map, and the honest thing is to say so
/// rather than to draw a grey rectangle where one would be: what the component
/// carries is places and legs, and those are readable as a list.
///
/// It is a named difference rather than a gap to be fixed quietly — see
/// `TestNothingIsPromisedThatCannotBeDrawn`. A real map here means a web view
/// factory over the same element, which needs the Flutter SDK to build and
/// verify, so it is not something to write blind.
Widget _googleMap(BuildContext context, TravelProps build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;

  final markers = build['markers'];
  final anchor = build['anchorMarker'];
  final routes = build['routes'];

  String labelOf(Object? pin) {
    if (pin is Map) {
      final label = pin['label']?.toString() ?? '';
      if (label.isNotEmpty) return label;
    }
    return '';
  }

  final pins = <String>[
    if (anchor != null && labelOf(anchor).isNotEmpty) labelOf(anchor),
    if (markers is List)
      for (final marker in markers)
        if (labelOf(marker).isNotEmpty) labelOf(marker),
  ];

  final legs = <String>[
    if (routes is List)
      for (final route in routes)
        if (route is Map &&
            labelOf(route['origin']).isNotEmpty &&
            labelOf(route['destination']).isNotEmpty)
          '${labelOf(route['origin'])} → ${labelOf(route['destination'])}',
  ];

  return Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: scheme.surfaceContainerHighest,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.map_outlined, size: 16, color: scheme.onSurfaceVariant),
            const SizedBox(width: 6),
            Text('Places on this map', style: text.labelMedium),
          ],
        ),
        if (legs.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(legs.join('  ·  '), style: text.bodySmall),
          ),
        if (pins.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final pin in pins)
                  Chip(
                    avatar: const Icon(Icons.place_outlined, size: 16),
                    label: Text(pin, style: text.labelSmall),
                    visualDensity: VisualDensity.compact,
                  ),
              ],
            ),
          ),
        if (pins.isEmpty && legs.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text('No places to show.', style: text.bodySmall),
          ),
      ],
    ),
  );
}

Widget _mapPreview(BuildContext context, TravelProps build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  // `markers`, which is what the catalog calls them. This read `places` and
  // so found nothing, every time: the chips below have never drawn. Nothing
  // failed, because a missing prop is an empty map and an empty map is an
  // empty row of chips.
  final places = build['markers'];
  return Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(
      color: scheme.surfaceContainerHighest,
      borderRadius: BorderRadius.circular(12),
    ),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            if (places is List)
              for (final place in places)
                if (place is Map)
                  Chip(
                    avatar: const Icon(Icons.place_outlined, size: 16),
                    label: Text(place['label']?.toString() ?? '', style: text.labelSmall),
                    visualDensity: VisualDensity.compact,
                  ),
          ],
        ),
        if (!build.pending('caption'))
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(build.string('caption') ?? '', style: text.bodySmall),
          ),
      ],
    ),
  );
}

/// A place this deployment flies, as an `AirportPicker` option.
class _Place {
  const _Place(this.value, this.label, this.code, this.detail);
  final String value;
  final String label;
  final String code;
  final String detail;
}

List<_Place> _placesOf(Object? options) => [
      if (options is List)
        for (final option in options.whereType<Map>())
          _Place(
            '${option['value'] ?? ''}',
            '${option['label'] ?? option['value'] ?? ''}',
            '${option['code'] ?? ''}',
            '${option['detail'] ?? ''}',
          ),
    ];

/// Best first: a code typed exactly, then names that start with what was typed.
List<_Place> _matching(List<_Place> places, String query) {
  final needle = query.trim().toLowerCase();
  if (needle.isEmpty) return places;
  int rank(_Place place) {
    final code = place.code.toLowerCase();
    final label = place.label.toLowerCase();
    if (code == needle) return 0;
    if (label.startsWith(needle)) return 1;
    if (code.startsWith(needle)) return 2;
    if (label.split(RegExp(r'[\s·,-]+')).any((word) => word.startsWith(needle))) return 3;
    if ('$label $code ${place.detail} ${place.value}'.toLowerCase().contains(needle)) return 4;
    return -1;
  }

  final ranked = [
    for (var index = 0; index < places.length; index++) (place: places[index], index: index, rank: rank(places[index])),
  ].where((entry) => entry.rank >= 0).toList()
    ..sort((a, b) => a.rank != b.rank ? a.rank - b.rank : a.index - b.index);
  return [for (final entry in ranked) entry.place];
}

/// Where from, where to: a field that opens a search sheet, the way a flight
/// app asks it on a phone. Writes the chosen place's `value` through the SDK's
/// binding and sends nothing, like every other editor.
Widget _airportPicker(BuildContext context, TravelProps build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  final places = _placesOf(build['options']);
  final value = build.string('value') ?? '';
  final chosen = places.where((place) => place.value == value).firstOrNull;
  final landing = build.string('kind') == 'destination';
  final label = build.string('label') ?? '';

  Future<void> search() async {
    final picked = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (_) => _PlaceSearch(places: places, chosen: value, title: label),
    );
    if (picked != null) build.write('value', picked);
  }

  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(label, style: text.labelLarge?.copyWith(fontWeight: FontWeight.w600)),
      const SizedBox(height: 6),
      _tappable(
        onTap: search,
        child: InputDecorator(
          isEmpty: chosen == null && value.isEmpty,
          decoration: InputDecoration(
            border: const OutlineInputBorder(),
            prefixIcon: Icon(landing ? Icons.flight_land : Icons.flight_takeoff, color: scheme.primary),
            hintText: build.string('placeholder') ?? 'City or airport',
          ),
          child: Row(
            children: [
              Expanded(
                child: Text(
                  chosen?.label ?? value,
                  style: text.titleMedium?.copyWith(fontWeight: FontWeight.w600),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (chosen != null && chosen.code.isNotEmpty) _CodeChip(chosen.code),
            ],
          ),
        ),
      ),
    ],
  );
}

class _CodeChip extends StatelessWidget {
  const _CodeChip(this.code);
  final String code;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        code,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              fontWeight: FontWeight.w700,
              letterSpacing: 0.6,
              color: scheme.onSurfaceVariant,
            ),
      ),
    );
  }
}

class _PlaceSearch extends StatefulWidget {
  const _PlaceSearch({required this.places, required this.chosen, required this.title});
  final List<_Place> places;
  final String chosen;
  final String title;

  @override
  State<_PlaceSearch> createState() => _PlaceSearchState();
}

class _PlaceSearchState extends State<_PlaceSearch> {
  String _query = '';

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final matches = _matching(widget.places, _query);
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.7,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: TextField(
                autofocus: true,
                decoration: InputDecoration(
                  hintText: widget.title.isEmpty ? 'City or airport' : widget.title,
                  prefixIcon: const Icon(Icons.search),
                  border: const OutlineInputBorder(),
                ),
                onChanged: (query) => setState(() => _query = query),
                onSubmitted: (_) {
                  if (matches.isNotEmpty) Navigator.pop(context, matches.first.value);
                },
              ),
            ),
            Expanded(
              child: matches.isEmpty
                  ? Center(child: Text('Nowhere called “${_query.trim()}” here'))
                  : ListView.builder(
                      itemCount: matches.length,
                      itemBuilder: (context, index) {
                        final place = matches[index];
                        final chosen = place.value == widget.chosen;
                        return ListTile(
                          leading: CircleAvatar(
                            backgroundColor: scheme.surfaceContainerHighest,
                            child: Icon(Icons.place_outlined, color: scheme.onSurfaceVariant, size: 20),
                          ),
                          title: Text(
                            place.label,
                            style: TextStyle(
                              fontWeight: FontWeight.w600,
                              color: chosen ? scheme.primary : null,
                            ),
                          ),
                          subtitle: place.detail.isEmpty ? null : Text(place.detail),
                          trailing: place.code.isEmpty ? null : _CodeChip(place.code),
                          onTap: () => Navigator.pop(context, place.value),
                        );
                      },
                    ),
            ),
          ],
        ),
      ),
    );
  }
}

Widget _travelerCounter(BuildContext context, TravelProps build) {
  final value = build.number('value')?.toInt() ?? 1;
  final min = build.number('min')?.toInt() ?? 1;
  final max = build.number('max')?.toInt() ?? 9;
  return Row(
    children: [
      Expanded(child: Text(build.string('label') ?? 'Travellers')),
      IconButton(
        onPressed: value > min ? () => build.write('value', value - 1) : null,
        icon: const Icon(Icons.remove_circle_outline),
      ),
      Text('$value', style: Theme.of(context).textTheme.titleMedium),
      IconButton(
        onPressed: value < max ? () => build.write('value', value + 1) : null,
        icon: const Icon(Icons.add_circle_outline),
      ),
    ],
  );
}

Widget _dateRangePicker(BuildContext context, TravelProps build) {
  final text = Theme.of(context).textTheme;
  final start = build.string('start');
  final end = build.string('end');

  Future<void> pick() async {
    final now = DateTime.now();
    final range = await showDateRangePicker(
      context: context,
      firstDate: now,
      lastDate: DateTime(now.year + 2),
      initialDateRange: (start != null && end != null)
          ? DateTimeRange(
              start: DateTime.tryParse(start) ?? now,
              end: DateTime.tryParse(end) ?? now.add(const Duration(days: 3)),
            )
          : null,
    );
    if (range == null) return;
    build.write('start', _calendarDate(range.start));
    build.write('end', _calendarDate(range.end));
  }

  return _tappable(
    onTap: pick,
    child: InputDecorator(
      decoration: InputDecoration(
        labelText: build.string('label') ?? 'Dates',
        border: const OutlineInputBorder(),
        isDense: true,
      ),
      child: Row(
        children: [
          Expanded(
            child: (start == null || start.isEmpty)
                ? const Text('Choose dates')
                // An en dash, not U+2192: the bundled Roboto subset has no
                // arrow, and a missing glyph draws a tofu box. See the note on
                // the icon in `_flightOption`.
                : Text('${_day(start)} – ${_day(end)}'),
          ),
          // The nights label is a `formatString` over `calcNights`, so it
          // recomputes as the picker moves rather than being written out this
          // turn and becoming wrong on the next drag.
          if (!build.pending('nightsLabel'))
            Text(build.string('nightsLabel') ?? '', style: text.bodySmall),
        ],
      ),
    ),
  );
}

String _day(String? iso) {
  final parsed = DateTime.tryParse(iso ?? '');
  if (parsed == null) return '—';
  return '${parsed.day}/${parsed.month}';
}

Widget _expenseSplit(BuildContext context, TravelProps build) {
  final text = Theme.of(context).textTheme;
  final people = build['people'];
  return Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    mainAxisSize: MainAxisSize.min,
    children: [
      Text(build.string('label') ?? 'Split', style: text.titleMedium),
      if (people is List)
        for (final person in people)
          if (person is Map)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 2),
              child: Row(
                children: [
                  Expanded(child: Text(person['name']?.toString() ?? '')),
                  Text(person['amount']?.toString() ?? ''),
                ],
              ),
            ),
    ],
  );
}

// ---------------------------------------------------------------------------
// TripCalendar
// ---------------------------------------------------------------------------

/// A civil date read off the front of a string — `2027-04-12`, or an RFC 3339
/// instant whose first ten characters are the day. Parsed as digits and built
/// in UTC, never through `DateTime.parse` on the whole string: that applies
/// the offset, and a departure west of Greenwich moves to the day before.
DateTime? _civilDate(Object? value) {
  if (value is! String) return null;
  final match = RegExp(r'^(\d{4})-(\d{2})-(\d{2})').firstMatch(value.trim());
  if (match == null) return null;
  final year = int.parse(match.group(1)!);
  final month = int.parse(match.group(2)!);
  final day = int.parse(match.group(3)!);
  if (month < 1 || month > 12) return null;
  final date = DateTime.utc(year, month, day);
  // `DateTime.utc(2027, 2, 30)` rolls to March rather than failing.
  if (date.month != month) return null;
  return date;
}

String _isoDay(DateTime date) =>
    '${date.year.toString().padLeft(4, '0')}-'
    '${date.month.toString().padLeft(2, '0')}-'
    '${date.day.toString().padLeft(2, '0')}';

/// The catalog's glyph names, in Material. Anything else is drawn as text —
/// an emoji, usually — which is what the `icon` field says it may hold.
const Map<String, IconData> _calendarGlyphs = {
  'plane': Icons.flight,
  'flight': Icons.flight,
  'bed': Icons.hotel,
  'stay': Icons.hotel,
  'hotel': Icons.hotel,
  'food': Icons.restaurant,
  'restaurant': Icons.restaurant,
  'sight': Icons.museum,
  'museum': Icons.museum,
  'transit': Icons.train,
  'outdoors': Icons.park,
  'shopping': Icons.shopping_bag,
  'event': Icons.event,
};

Widget _calendarGlyph(String name, Color colour, double size) {
  final icon = _calendarGlyphs[name.toLowerCase()];
  if (icon != null) return Icon(icon, size: size, color: colour);
  return Text(name, style: TextStyle(fontSize: size * 0.85, height: 1));
}

Widget _tripCalendar(BuildContext context, TravelProps build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  final locale = MaterialLocalizations.of(context);

  final start = _civilDate(build['start']);
  var end = _civilDate(build['end']);
  // No end, or one before the start, is a single day: a range being edited
  // passes through inverted, and vanishing at that moment is worse than
  // drawing the one day that is certainly true.
  if (start != null && (end == null || end.isBefore(start))) end = start;

  final marks = <String, (String, String)>{};
  final rawMarks = build['marks'];
  if (rawMarks is List) {
    for (final mark in rawMarks) {
      if (mark is! Map) continue;
      final day = _civilDate(mark['date']);
      if (day == null) continue;
      marks[_isoDay(day)] = (mark['icon']?.toString() ?? '', mark['label']?.toString() ?? '');
    }
  }
  // Each glyph once in the key, with what it means.
  final key = <String, String>{};
  for (final (icon, label) in marks.values) {
    if (icon.isNotEmpty && label.isNotEmpty) key['$icon\u0000$label'] = label;
  }

  // 0 = Sunday … 6 = Saturday, as Material counts; DateTime counts Monday as 1.
  final firstDay = locale.firstDayOfWeekIndex;
  final letters = locale.narrowWeekdays;

  final months = <Widget>[];
  if (start != null && end != null) {
    var year = start.year;
    var month = start.month;
    // Capped so a typo in a year does not draw three hundred grids.
    while (months.length < 4) {
      months.add(_calendarMonth(
        context,
        year: year,
        month: month,
        start: start,
        end: end,
        firstDay: firstDay,
        letters: letters,
        marks: marks,
      ));
      if (year == end.year && month == end.month) break;
      month += 1;
      if (month > 12) {
        month = 1;
        year += 1;
      }
    }
  }

  final body = Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      if (!build.pending('title'))
        Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Text(build.string('title') ?? '', style: text.labelLarge),
        ),
      if (months.isEmpty)
        Text('Dates to come', style: text.bodySmall?.copyWith(fontStyle: FontStyle.italic))
      else
        Wrap(spacing: 20, runSpacing: 12, children: months),
      if (key.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Wrap(
            spacing: 12,
            runSpacing: 4,
            children: [
              for (final entry in key.entries)
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _calendarGlyph(entry.key.split('\u0000').first, scheme.primary, 14),
                    const SizedBox(width: 4),
                    Text(entry.value, style: text.bodySmall),
                  ],
                ),
            ],
          ),
        ),
      if (!build.pending('caption'))
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(build.string('caption') ?? '', style: text.bodySmall),
        ),
    ],
  );

  return _tappable(
    onTap: build.hasAction ? build.fire : null,
    child: Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: scheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: body,
    ),
  );
}

/// One month: its name, then whole weeks of 32-point cells with the travel
/// band drawn on the cell backgrounds so it wraps across rows for free.
Widget _calendarMonth(
  BuildContext context, {
  required int year,
  required int month,
  required DateTime start,
  required DateTime end,
  required int firstDay,
  required List<String> letters,
  required Map<String, (String, String)> marks,
}) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  final total = DateTime.utc(year, month + 1, 0).day;
  // DateTime.weekday is 1 (Monday) … 7 (Sunday); Material's index is
  // 0 (Sunday) … 6 (Saturday).
  final leading = (DateTime.utc(year, month, 1).weekday % 7 - firstDay + 7) % 7;
  final cells = <Widget>[];
  for (var i = 0; i < leading; i += 1) {
    cells.add(const SizedBox(width: 32, height: 32));
  }

  for (var day = 1; day <= total; day += 1) {
    final date = DateTime.utc(year, month, day);
    final inRange = !date.isBefore(start) && !date.isAfter(end);
    final isStart = date == start;
    final isEnd = date == end;
    final mark = marks[_isoDay(date)];
    final number = Text(
      '$day',
      style: text.bodySmall?.copyWith(
        fontWeight: inRange ? FontWeight.w600 : FontWeight.w400,
        color: (isStart || isEnd)
            ? scheme.onPrimary
            : inRange
                ? scheme.onSurface
                : scheme.onSurfaceVariant,
      ),
    );
    cells.add(Container(
      width: 32,
      height: 32,
      decoration: inRange
          ? BoxDecoration(
              color: scheme.primary.withValues(alpha: 0.12),
              borderRadius: BorderRadius.horizontal(
                left: isStart ? const Radius.circular(16) : Radius.zero,
                right: isEnd ? const Radius.circular(16) : Radius.zero,
              ),
            )
          : null,
      child: Stack(
        alignment: Alignment.center,
        children: [
          if (isStart || isEnd)
            Container(
              width: 26,
              height: 26,
              decoration: BoxDecoration(color: scheme.primary, shape: BoxShape.circle),
            ),
          number,
          if (mark != null && mark.$1.isNotEmpty)
            Positioned(
              right: 1,
              top: (isStart || isEnd) ? -1 : null,
              bottom: (isStart || isEnd) ? null : 1,
              child: _calendarGlyph(mark.$1, scheme.primary, 10),
            ),
        ],
      ),
    ));
  }
  while (cells.length % 7 != 0) {
    cells.add(const SizedBox(width: 32, height: 32));
  }

  final monthName = MaterialLocalizations.of(context).formatMonthYear(DateTime.utc(year, month, 1));
  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Padding(
        padding: const EdgeInsets.only(left: 4, bottom: 4),
        child: Text(monthName, style: text.titleSmall),
      ),
      Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          for (var i = 0; i < 7; i += 1)
            SizedBox(
              width: 32,
              child: Text(
                letters[(firstDay + i) % 7],
                textAlign: TextAlign.center,
                style: text.labelSmall?.copyWith(color: scheme.outline),
              ),
            ),
        ],
      ),
      for (var row = 0; row < cells.length; row += 7)
        Padding(
          padding: const EdgeInsets.only(bottom: 2),
          child: Row(mainAxisSize: MainAxisSize.min, children: cells.sublist(row, row + 7)),
        ),
    ],
  );
}


/// The travel views by component name.
const Map<String, TravelView> travelViews = {
  'ActivityItem': _activityItem,
  'AirportPicker': _airportPicker,
  'DateRangePicker': _dateRangePicker,
  'ExpenseSplit': _expenseSplit,
  'FlightOption': _flightOption,
  'GoogleMap': _googleMap,
  'HotelCard': _hotelCard,
  'ItineraryDay': _itineraryDay,
  'MapPreview': _mapPreview,
  'PriceSummary': _priceSummary,
  'ProgressMeter': _progressMeter,
  'StatTile': _statTile,
  'TravelerCounter': _travelerCounter,
  'TripCalendar': _tripCalendar,
  'WeatherStrip': _weatherStrip,
};

/// A travel view as an `a2ui_flutter` component, against the catalog's schema.
ComponentImplementation travelComponent(ComponentApi api, TravelView view) => ComponentImplementation(
      name: api.name,
      schema: api.schema,
      allowedParents: api.allowedParents,
      allowedChildren: api.allowedChildren,
      builder: (context, node, props, buildChild) => view(context, TravelProps(props, buildChild)),
    );
