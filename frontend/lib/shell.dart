import 'package:flutter/material.dart';

import 'theme.dart';
import 'today/today_screen.dart';

/// Bottom tabs: Today · Calendar · Projects · Week.
class Shell extends StatefulWidget {
  const Shell({super.key});

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _tab = 0;

  static const _tabs = [
    (icon: Icons.format_list_bulleted_rounded, label: 'Today'),
    (icon: Icons.calendar_today_outlined, label: 'Calendar'),
    (icon: Icons.grid_view_rounded, label: 'Projects'),
    (icon: Icons.bar_chart_rounded, label: 'Week'),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        bottom: false,
        child: IndexedStack(index: _tab, children: [
          const TodayScreen(),
          for (final t in _tabs.skip(1)) _ComingSoon(t.label),
        ]),
      ),
      bottomNavigationBar: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 2, 12, 4),
          child: Row(children: [
            for (final (i, t) in _tabs.indexed)
              Expanded(
                child: Semantics(
                  selected: i == _tab,
                  button: true,
                  label: t.label,
                  excludeSemantics: true,
                  child: InkResponse(
                    onTap: () => setState(() => _tab = i),
                    child: SizedBox(
                      height: 50,
                      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                        Icon(t.icon, size: 22, color: i == _tab ? Palette.red : Palette.muted),
                        const SizedBox(height: 3),
                        Text(t.label, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600,
                            color: i == _tab ? Palette.red : Palette.muted)),
                      ]),
                    ),
                  ),
                ),
              ),
          ]),
        ),
      ),
    );
  }
}

class _ComingSoon extends StatelessWidget {
  const _ComingSoon(this.title);
  final String title;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w700, letterSpacing: -0.6)),
          const SizedBox(height: 8),
          const Text('Coming next.', style: TextStyle(color: Palette.muted, fontSize: 15)),
        ]),
      );
}
