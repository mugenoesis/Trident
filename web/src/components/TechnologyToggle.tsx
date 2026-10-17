import type { Technology } from '../hooks/useResin';

const CHOICES: { value: Technology; label: string }[] = [
	{ value: 'fdm', label: 'FDM' },
	{ value: 'resin', label: 'Resin' },
];

// Switches the right-hand panel between filament printers and resin printers.
export default function TechnologyToggle({ technology, onChange }: { technology: Technology; onChange: (t: Technology) => void }) {
	return (
		<fieldset className="technology-toggle" aria-label="Printer technology">
			{CHOICES.map(({ value, label }) => (
				<button
					key={value}
					type="button"
					className={technology === value ? 'selected' : ''}
					aria-pressed={technology === value}
					onClick={() => onChange(value)}
				>
					{label}
				</button>
			))}
		</fieldset>
	);
}
