import { useEffect, useState } from 'react';
import { getModel } from '../api';

// Support points sent with the model (placed by hand in Holecraft): how many there are, and whether the slice should use them.
export function useHandPlacedSupports(modelId: string | null, active: boolean) {
	const [count, setCount] = useState<number | null>(null);
	const [use, setUse] = useState(true);
	useEffect(() => {
		setCount(null);
		setUse(true);
		if (!modelId || !active) return;
		let current = true;
		getModel(modelId)
			.then((model) => current && setCount(model.support_point_count ?? null))
			.catch(() => undefined);
		return () => {
			current = false;
		};
	}, [modelId, active]);
	return { count, use, setUse };
}
