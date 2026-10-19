import type { FieldTags } from '../klipperImport';
import type { Fields } from './PrinterDialog';

/** The small tag beside a field's label that says its value was read from the printer (or needs a second look): it goes once the user types something else. */
export default function FieldTag({ tags, f, field }: { tags: FieldTags; f: Fields; field: keyof Fields }) {
	const tag = tags[field];
	if (!tag || String(f[field]) !== tag.value) return null;
	return (
		<span className="field-tag" data-tag={tag.kind} aria-hidden="true">
			{tag.kind === 'check' ? 'check' : 'from printer'}
		</span>
	);
}
