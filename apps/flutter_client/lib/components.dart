// The widgets. This is the only file in the client that knows what a trip
// looks like — and even here, it knows only how to *draw* one.
//
// Each builder receives properties that are already resolved: the core's binder
// has walked the schema, followed every binding into the data model, run every
// function call, and handed over plain values. So nothing here reads a path or
// evaluates an expression, which is what keeps a component a component.
//
// The one idea worth carrying from the React renderer is the pending state. A
// binding whose path does not resolve is *pending*; a path resolving to an
// empty string is *empty*. That distinction is not a convention invented here —
// it falls out of the data model — and it is what lets a surface paint its
// layout the moment a search starts and fill in when the rows land.

import 'package:a2ui_core/a2ui_core.dart';
import 'package:flutter/material.dart';

/// What a builder is given: resolved properties, and a way to send an action.
class ComponentBuild {
  ComponentBuild({
    required this.props,
    required this.context,
    required this.child,
    required this.children,
  });

  final Map<String, dynamic> props;
  final ComponentContext context;

  /// Draws one child by id.
  final Widget Function(String id) child;

  /// Draws a property that holds a child list or a template.
  final List<Widget> Function(String property) children;

  String? string(String key) {
    final value = props[key];
    if (value == null) return null;
    final text = value.toString();
    return text.isEmpty ? '' : text;
  }

  num? number(String key) {
    final value = props[key];
    if (value is num) return value;
    if (value is String) return num.tryParse(value);
    return null;
  }

  bool flag(String key) => props[key] == true;

  /// True when a property is *waiting* rather than empty.
  ///
  /// The whole of the skeleton state rests on this. A price that has not
  /// arrived is `null` because its path does not resolve; a price that is
  /// genuinely blank is `''`. Treating them alike paints four flights with no
  /// airline and no fare, which looks like an answer and is worse than a
  /// spinner.
  bool pending(String key) => !props.containsKey(key) || props[key] == null;

  void send(String name, [Map<String, dynamic> payload = const {}]) {
    context.dispatchAction({
      'event': {'name': name, 'context': payload},
    });
  }

  /// Whether this component declares an action.
  ///
  /// The binder resolves an action property into a *closure* that dispatches
  /// it, rather than into the map the message carried — so this asks whether
  /// there is something to call. Reading it as a map instead finds nothing,
  /// every button renders disabled, and the surface looks finished rather than
  /// broken.
  bool get hasAction => props['action'] is Function;

  /// Fires the declared action: an event back to the agent, or a catalog
  /// function run here in the renderer.
  void fire() {
    final declared = props['action'];
    if (declared is Function) declared();
  }

  /// Writes a value back into the data model at a bound path.
  ///
  /// Editors change the data model and send nothing. That is the interaction
  /// model, not an optimisation: dragging a slider is somebody still answering,
  /// and only a button means they are done.
  void write(String key, Object? value) {
    final binding = context.componentModel.properties[key];
    final path = binding is Map ? binding['path'] : null;
    if (path is String) {
      context.surface.dataModel.set(path, value);
    }
  }
}

typedef ComponentBuilder = Widget Function(BuildContext, ComponentBuild);

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
Widget _bound(ComponentBuild build, String key, TextStyle? style, {double width = 64}) {
  if (build.pending(key)) return _Pending(width: width);
  return Text(build.string(key) ?? '', style: style);
}

// ---------------------------------------------------------------------------
// Layout and basics
// ---------------------------------------------------------------------------

Widget _text(BuildContext context, ComponentBuild build) {
  final theme = Theme.of(context).textTheme;
  final style = switch (build.string('variant')) {
    'h1' => theme.headlineLarge,
    'h2' => theme.headlineMedium,
    'h3' => theme.titleLarge,
    'h4' => theme.titleMedium,
    'h5' => theme.titleSmall,
    'caption' => theme.bodySmall?.copyWith(
        color: Theme.of(context).colorScheme.onSurfaceVariant,
      ),
    _ => theme.bodyMedium,
  };
  if (build.pending('text')) return const _Pending(width: 120);
  return Text(build.string('text') ?? '', style: style);
}

Widget _column(BuildContext context, ComponentBuild build) {
  return Column(
    crossAxisAlignment: switch (build.string('align')) {
      'center' => CrossAxisAlignment.center,
      'end' => CrossAxisAlignment.end,
      'stretch' => CrossAxisAlignment.stretch,
      _ => CrossAxisAlignment.start,
    },
    mainAxisSize: MainAxisSize.min,
    children: [
      for (final child in build.children('children'))
        Padding(padding: const EdgeInsets.only(bottom: 8), child: child),
    ],
  );
}

Widget _row(BuildContext context, ComponentBuild build) {
  return Row(
    mainAxisAlignment: switch (build.string('justify')) {
      'center' => MainAxisAlignment.center,
      'end' => MainAxisAlignment.end,
      'spaceBetween' => MainAxisAlignment.spaceBetween,
      'spaceAround' => MainAxisAlignment.spaceAround,
      'spaceEvenly' => MainAxisAlignment.spaceEvenly,
      _ => MainAxisAlignment.start,
    },
    crossAxisAlignment: switch (build.string('align')) {
      'center' => CrossAxisAlignment.center,
      'end' => CrossAxisAlignment.end,
      'stretch' => CrossAxisAlignment.stretch,
      _ => CrossAxisAlignment.start,
    },
    children: [
      for (final child in build.children('children'))
        Flexible(child: Padding(padding: const EdgeInsets.only(right: 8), child: child)),
    ],
  );
}

Widget _list(BuildContext context, ComponentBuild build) => Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (final child in build.children('children'))
          Padding(padding: const EdgeInsets.only(bottom: 8), child: child),
      ],
    );

Widget _card(BuildContext context, ComponentBuild build) => Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: build.children('children'),
        ),
      ),
    );

Widget _divider(BuildContext context, ComponentBuild build) => const Divider();

Widget _button(BuildContext context, ComponentBuild build) {
  // A Button's face is a *component*, not a string — the catalog says
  // `Button(Text("Apply"), …)` — so the label is drawn by whatever that child
  // turns out to be. `label` is accepted as well because a model writes it
  // often enough, and refusing it would render an unlabelled button.
  final children = build.children('child');
  final Widget face = children.isNotEmpty
      ? children.first
      : Text(build.string('label') ?? build.string('text') ?? 'Continue');

  final onPressed = build.hasAction ? build.fire : null;

  return switch (build.string('variant') ?? build.string('style')) {
    'borderless' => TextButton(onPressed: onPressed, child: face),
    'secondary' => OutlinedButton(onPressed: onPressed, child: face),
    _ => FilledButton(onPressed: onPressed, child: face),
  };
}

// ---------------------------------------------------------------------------
// Travel
// ---------------------------------------------------------------------------

/// The catalog's icon names, mapped to Material's.
///
/// The catalog names 59 icons in its own lower-camel spelling, which is the
/// protocol's vocabulary and deliberately not any one toolkit's. Flutter did
/// not draw `Icon` at all, so every one of them came out as a placeholder box —
/// while the model was being told it could use them, because pruning removes
/// `Divider` (which Flutter *can* draw) and keeps `Icon` (which it could not).
///
/// An unknown name falls through to a neutral dot rather than to nothing: a
/// missing icon should leave the row the right shape.
const Map<String, IconData> _iconNames = {
  'accountCircle': Icons.account_circle,
  'add': Icons.add,
  'arrowBack': Icons.arrow_back,
  'arrowForward': Icons.arrow_forward,
  'attachFile': Icons.attach_file,
  'calendarToday': Icons.calendar_today,
  'call': Icons.call,
  'camera': Icons.camera_alt,
  'check': Icons.check,
  'close': Icons.close,
  'delete': Icons.delete,
  'download': Icons.download,
  'edit': Icons.edit,
  'event': Icons.event,
  'error': Icons.error,
  'fastForward': Icons.fast_forward,
  'favorite': Icons.favorite,
  'favoriteOff': Icons.favorite_border,
  'folder': Icons.folder,
  'help': Icons.help,
  'home': Icons.home,
  'info': Icons.info,
  'locationOn': Icons.location_on,
  'lock': Icons.lock,
  'lockOpen': Icons.lock_open,
  'mail': Icons.mail,
  'menu': Icons.menu,
  'moreVert': Icons.more_vert,
  'moreHoriz': Icons.more_horiz,
  'notificationsOff': Icons.notifications_off,
  'notifications': Icons.notifications,
  'pause': Icons.pause,
  'payment': Icons.payment,
  'person': Icons.person,
  'phone': Icons.phone,
  'photo': Icons.photo,
  'play': Icons.play_arrow,
  'print': Icons.print,
  'refresh': Icons.refresh,
  'rewind': Icons.fast_rewind,
  'search': Icons.search,
  'send': Icons.send,
  'settings': Icons.settings,
  'share': Icons.share,
  'shoppingCart': Icons.shopping_cart,
  'skipNext': Icons.skip_next,
  'skipPrevious': Icons.skip_previous,
  'star': Icons.star,
  'starHalf': Icons.star_half,
  'starOff': Icons.star_border,
  'stop': Icons.stop,
  'upload': Icons.upload,
  'visibility': Icons.visibility,
  'visibilityOff': Icons.visibility_off,
  'volumeDown': Icons.volume_down,
  'volumeMute': Icons.volume_mute,
  'volumeOff': Icons.volume_off,
  'volumeUp': Icons.volume_up,
  'warning': Icons.warning,
};

Widget _icon(BuildContext context, ComponentBuild build) {
  final name = build.string('name') ?? '';
  return Icon(
    _iconNames[name] ?? Icons.circle,
    size: 18,
    color: Theme.of(context).colorScheme.onSurfaceVariant,
  );
}

Widget _flightOption(BuildContext context, ComponentBuild build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  final badge = build.string('badge');

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
              Expanded(child: _bound(build, 'airline', text.titleMedium, width: 90)),
              if (badge != null && badge.isNotEmpty)
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(
                    color: scheme.secondaryContainer,
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(badge, style: text.labelSmall),
                ),
              const SizedBox(width: 8),
              _bound(build, 'price', text.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                  width: 56),
            ],
          ),
          const SizedBox(height: 8),
          Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              _bound(build, 'departTime', text.bodyLarge, width: 48),
              const SizedBox(width: 6),
              // A Material icon rather than U+2192: the bundled Roboto subset
              // does not carry that arrow, and a missing glyph renders as a
              // tofu box — which reads as a broken card rather than a missing
              // character.
              Icon(Icons.arrow_right_alt, size: 16, color: scheme.onSurfaceVariant),
              const SizedBox(width: 6),
              _bound(build, 'arriveTime', text.bodyLarge, width: 48),
              const SizedBox(width: 12),
              Flexible(
                child: _bound(build, 'origin', text.bodySmall, width: 32),
              ),
              Text(' · ', style: text.bodySmall),
              Flexible(
                child: _bound(build, 'destination', text.bodySmall, width: 32),
              ),
            ],
          ),
          const SizedBox(height: 4),
          DefaultTextStyle(
            style: text.bodySmall!.copyWith(color: scheme.onSurfaceVariant),
            child: Row(
              children: [
                _bound(build, 'duration', text.bodySmall, width: 54),
                const SizedBox(width: 10),
                _bound(build, 'stops', text.bodySmall, width: 70),
                const Spacer(),
                _bound(build, 'flightNumber', text.bodySmall, width: 48),
              ],
            ),
          ),
        ],
      ),
    ),
  );
}

Widget _hotelCard(BuildContext context, ComponentBuild build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  final amenities = build.props['amenities'];

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

Widget _statTile(BuildContext context, ComponentBuild build) {
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

Widget _progressMeter(BuildContext context, ComponentBuild build) {
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

Widget _priceSummary(BuildContext context, ComponentBuild build) {
  final text = Theme.of(context).textTheme;
  final lines = build.props['lines'];
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

Widget _itineraryDay(BuildContext context, ComponentBuild build) {
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
      ],
    ),
  );
}

Widget _activityItem(BuildContext context, ComponentBuild build) {
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
      ],
    ),
  );
}

Widget _weatherStrip(BuildContext context, ComponentBuild build) {
  final text = Theme.of(context).textTheme;
  final days = build.props['days'];
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

Widget _mapPreview(BuildContext context, ComponentBuild build) {
  final scheme = Theme.of(context).colorScheme;
  final text = Theme.of(context).textTheme;
  final places = build.props['places'];
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

// ---------------------------------------------------------------------------
// Editors — they change the data model and send nothing
// ---------------------------------------------------------------------------

Widget _textField(BuildContext context, ComponentBuild build) {
  return _LiveTextField(build: build);
}

class _LiveTextField extends StatefulWidget {
  const _LiveTextField({required this.build});

  final ComponentBuild build;

  @override
  State<_LiveTextField> createState() => _LiveTextFieldState();
}

class _LiveTextFieldState extends State<_LiveTextField> {
  late final TextEditingController _controller =
      TextEditingController(text: widget.build.string('text') ?? '');

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  void didUpdateWidget(_LiveTextField old) {
    super.didUpdateWidget(old);
    // The server seeds `/trip` into a surface as it is created, so a control
    // opens showing what is already decided. Only adopt the incoming value when
    // it differs, or every keystroke would fight the rebuild.
    final incoming = widget.build.string('text') ?? '';
    if (incoming != _controller.text && !_controller.selection.isValid) {
      _controller.text = incoming;
    }
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _controller,
      decoration: InputDecoration(
        labelText: widget.build.string('label'),
        border: const OutlineInputBorder(),
        isDense: true,
      ),
      onChanged: (value) => widget.build.write('text', value),
    );
  }
}

Widget _checkBox(BuildContext context, ComponentBuild build) => CheckboxListTile(
      contentPadding: EdgeInsets.zero,
      controlAffinity: ListTileControlAffinity.leading,
      dense: true,
      value: build.flag('value'),
      title: Text(build.string('label') ?? ''),
      onChanged: (value) => build.write('value', value ?? false),
    );

Widget _slider(BuildContext context, ComponentBuild build) {
  final min = build.number('min')?.toDouble() ?? 0;
  final max = build.number('max')?.toDouble() ?? 100;
  final value = (build.number('value')?.toDouble() ?? min).clamp(min, max).toDouble();
  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      Row(
        children: [
          Expanded(child: Text(build.string('label') ?? '')),
          Text(value.round().toString()),
        ],
      ),
      Slider(
        min: min,
        max: max,
        value: value,
        onChanged: (next) => build.write('value', next.round()),
      ),
    ],
  );
}

Widget _choicePicker(BuildContext context, ComponentBuild build) {
  final options = build.props['options'];
  final selected = build.props['value'];
  final multiple = build.string('selection') == 'multiple';

  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    mainAxisSize: MainAxisSize.min,
    children: [
      if (!build.pending('label')) Text(build.string('label') ?? ''),
      const SizedBox(height: 4),
      Wrap(
        spacing: 6,
        runSpacing: 6,
        children: [
          if (options is List)
            for (final option in options)
              if (option is Map)
                ChoiceChip(
                  label: Text(option['label']?.toString() ?? ''),
                  selected: multiple
                      ? (selected is List && selected.contains(option['value']))
                      : selected == option['value'],
                  onSelected: (_) => build.write('value', option['value']),
                ),
        ],
      ),
    ],
  );
}

Widget _travelerCounter(BuildContext context, ComponentBuild build) {
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

Widget _dateRangePicker(BuildContext context, ComponentBuild build) {
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
    build.write('start', range.start.toIso8601String());
    build.write('end', range.end.toIso8601String());
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

Widget _dateTimeInput(BuildContext context, ComponentBuild build) {
  final value = build.string('value');
  return _tappable(
    onTap: () async {
      final now = DateTime.now();
      final picked = await showDatePicker(
        context: context,
        firstDate: now,
        lastDate: DateTime(now.year + 2),
        initialDate: DateTime.tryParse(value ?? '') ?? now,
      );
      if (picked != null) build.write('value', picked.toIso8601String());
    },
    child: InputDecorator(
      decoration: InputDecoration(
        labelText: build.string('label'),
        border: const OutlineInputBorder(),
        isDense: true,
      ),
      child: Text((value == null || value.isEmpty) ? 'Choose a date' : _day(value)),
    ),
  );
}

Widget _expenseSplit(BuildContext context, ComponentBuild build) {
  final text = Theme.of(context).textTheme;
  final people = build.props['people'];
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
// Components the catalog has and this client does not draw specially
// ---------------------------------------------------------------------------

Widget _placeholder(String name) => Builder(
      builder: (context) {
        final scheme = Theme.of(context).colorScheme;
        return Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            border: Border.all(color: scheme.outlineVariant, style: BorderStyle.solid),
            borderRadius: BorderRadius.circular(8),
          ),
          // Named rather than blank. A component this client has not learned yet
          // should be visibly missing, not invisibly missing — the second is how
          // a gap in a surface gets mistaken for a gap in the answer.
          child: Text(
            '$name is not drawn by this client yet',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        );
      },
    );

/// The builder for a component name.
ComponentBuilder builderFor(String name) {
  final builder = _builders[name];
  if (builder != null) return builder;
  return (context, build) => _placeholder(name);
}

/// Names this client draws with a real widget.
Set<String> get drawnComponents => _builders.keys.toSet();

final Map<String, ComponentBuilder> _builders = {
  'Text': _text,
  'Column': _column,
  'Row': _row,
  'List': _list,
  'Card': _card,
  'Divider': _divider,
  'Icon': _icon,
  'Button': _button,
  'TextField': _textField,
  'CheckBox': _checkBox,
  'Slider': _slider,
  'ChoicePicker': _choicePicker,
  'DateTimeInput': _dateTimeInput,
  'DateRangePicker': _dateRangePicker,
  'TravelerCounter': _travelerCounter,
  'FlightOption': _flightOption,
  'HotelCard': _hotelCard,
  'ItineraryDay': _itineraryDay,
  'ActivityItem': _activityItem,
  'MapPreview': _mapPreview,
  'PriceSummary': _priceSummary,
  'StatTile': _statTile,
  'ProgressMeter': _progressMeter,
  'WeatherStrip': _weatherStrip,
  'ExpenseSplit': _expenseSplit,
};
