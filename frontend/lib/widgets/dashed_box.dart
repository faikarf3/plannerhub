import 'package:flutter/material.dart';

/// A rounded box with a dashed outline (planned blocks on the calendar).
class DashedBox extends StatelessWidget {
  const DashedBox({super.key, required this.color, required this.child, this.radius = 6, this.fill});

  final Color color;
  final Color? fill;
  final double radius;
  final Widget child;

  @override
  Widget build(BuildContext context) => CustomPaint(
        painter: _DashedPainter(color, radius, fill),
        child: child,
      );
}

class _DashedPainter extends CustomPainter {
  _DashedPainter(this.color, this.radius, this.fill);
  final Color color;
  final double radius;
  final Color? fill;

  @override
  void paint(Canvas canvas, Size size) {
    final rrect = RRect.fromRectAndRadius(Offset.zero & size, Radius.circular(radius)).deflate(0.75);
    if (fill != null) canvas.drawRRect(rrect, Paint()..color = fill!);
    final stroke = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;
    for (final metric in (Path()..addRRect(rrect)).computeMetrics()) {
      for (double d = 0; d < metric.length; d += 7) {
        canvas.drawPath(metric.extractPath(d, d + 4), stroke);
      }
    }
  }

  @override
  bool shouldRepaint(_DashedPainter old) => old.color != color || old.fill != fill;
}
