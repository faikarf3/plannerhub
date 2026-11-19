import 'package:flutter/material.dart';

import '../api/models.dart';
import '../sheets/clock_in_sheet.dart' show jobs;
import 'common.dart';

/// Category chips, plus job chips when the category is paid work (the backend
/// requires a job there).
class CategoryPicker extends StatelessWidget {
  const CategoryPicker({super.key, required this.categories, required this.categoryId,
      required this.job, required this.onChanged});

  final List<Category> categories;
  final int? categoryId;
  final String? job;
  final void Function(int categoryId, String? job) onChanged;

  @override
  Widget build(BuildContext context) {
    final selected = categories.where((c) => c.id == categoryId).firstOrNull;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const FieldLabel('What'),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final c in categories)
          OptionChip(label: c.name, selected: c.id == categoryId,
              onTap: () => onChanged(c.id, c.isWork ? job : null)),
      ]),
      if (selected?.isWork ?? false) ...[
        const SizedBox(height: 14),
        const FieldLabel('Job'),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final e in jobs.entries)
            OptionChip(label: e.value, selected: e.key == job, onTap: () => onChanged(selected!.id, e.key)),
        ]),
      ],
    ]);
  }
}

/// True when the choice is complete (work needs a job).
bool categoryComplete(List<Category> categories, int? categoryId, String? job) {
  final c = categories.where((c) => c.id == categoryId).firstOrNull;
  return c != null && (!c.isWork || job != null);
}
