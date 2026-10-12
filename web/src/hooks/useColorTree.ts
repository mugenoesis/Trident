import { useMemo } from 'react';
import type { ColorNode } from '../types';
import type { AppState, MainAppProps } from './useAppState';

export function useColorTree(c: AppState & Pick<MainAppProps, never>) {
	const { roleNozzleAssignments, filamentSlots, plateInfo } = c;

	// The 3D preview should show what will actually print -- once a role has
	// a nozzle assigned, substitute that slot's own color for the file's
	// original one; a role with no assignment yet keeps showing the file's
	// color as a placeholder. Recomputed on every assignment change, which
	// is what makes the preview update live as roles are picked.
	const renderColorTree = useMemo(() => {
		const assignedColorFor = (extruder: number | null): string | undefined => {
			if (extruder === null) return undefined;
			const slotIdx = roleNozzleAssignments[extruder - 1];
			return slotIdx !== null ? filamentSlots[slotIdx]?.color : undefined;
		};
		const substitute = (nodes: ColorNode[]): ColorNode[] =>
			nodes.map((node) => {
				if (node.children.length > 0) return { ...node, children: substitute(node.children) };
				const assignedColor = assignedColorFor(node.extruder);
				const triangleColors = node.triangle_extruders
					? node.triangle_extruders.map((extruder, i) => assignedColorFor(extruder) ?? node.triangle_colors?.[i] ?? null)
					: node.triangle_colors;
				if (!assignedColor && triangleColors === node.triangle_colors) return node;
				return { ...node, color: assignedColor ?? node.color, triangle_colors: triangleColors ?? null };
			});
		return substitute(plateInfo?.color_tree ?? []);
	}, [plateInfo, roleNozzleAssignments, filamentSlots]);
	return { renderColorTree };
}
