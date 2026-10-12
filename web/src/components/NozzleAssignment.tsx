import { colorLabel } from '../appHelpers';
import type { AppCtx } from '../hooks/useAppController';

// Which nozzle prints each colour of the file.
export default function NozzleAssignment({ c }: { c: AppCtx }) {
	const { modelId, showNozzleAssignment, fileRoles, roleNozzleAssignments, setRoleNozzleAssignments, filamentSlots } = c;
	return (
		<>
			{modelId && showNozzleAssignment && (
				<div className="field-group nozzle-assignment">
					<span>
						{fileRoles.length > 1 ? 'This file uses multiple colors -- assign each to a nozzle' : 'Which nozzle should print this?'}
					</span>
					{fileRoles.map((role, roleIdx) => (
						// biome-ignore lint/suspicious/noArrayIndexKey: a fixed, position-ordered list that is never reordered
						<div className="nozzle-assignment-row" key={roleIdx}>
							{fileRoles.length > 1 && (
								<>
									<span
										className="nozzle-assignment-role-swatch"
										style={role.color ? { background: role.color } : undefined}
										title={role.color ?? 'Unknown color'}
									/>
									<span className="nozzle-assignment-role-label">
										Color {roleIdx + 1}
										{role.name ? ` — ${role.name}` : ''}
									</span>
								</>
							)}
							<select
								value={roleNozzleAssignments[roleIdx] ?? ''}
								onChange={(e) => {
									const value = e.target.value === '' ? null : Number(e.target.value);
									setRoleNozzleAssignments((prev) => prev.map((v, i) => (i === roleIdx ? value : v)));
								}}
							>
								<option value="" disabled>
									Choose a nozzle…
								</option>
								{filamentSlots.map((slot, slotIdx) => (
									// biome-ignore lint/suspicious/noArrayIndexKey: a fixed, position-ordered list that is never reordered
									<option key={slotIdx} value={slotIdx}>
										{`Slot ${slotIdx + 1} (${colorLabel(slot.color)})${slot.profile ? ` — ${slot.profile}` : ''}`}
									</option>
								))}
							</select>
						</div>
					))}
				</div>
			)}
		</>
	);
}
