import { useEffect, useState } from 'react';
import { printerSnapshotUrl } from '../api';
import type { PrinterCamera } from '../types';

/** How often a new picture is fetched while the card shows a camera. */
const REFRESH_MS = 1000;

/**
 * A printer's webcam as a picture that is renewed about once a second: each new picture is loaded out of sight and swapped in when it has
 * arrived, so the picture never flickers. The pictures come through the server (the printer's address and key stay there).
 */
export default function PrinterCam({ printerId, cameras }: { printerId: string; cameras: PrinterCamera[] }) {
	const [chosen, setChosen] = useState(0);
	const [src, setSrc] = useState<string | null>(null);
	const [failed, setFailed] = useState(false);
	const camera = cameras[chosen] ?? cameras[0];

	useEffect(() => {
		if (!camera) return;
		let alive = true;
		let tick = 0;
		let timer: ReturnType<typeof setTimeout> | undefined;
		const fetchNext = () => {
			const next = new Image();
			next.onload = () => {
				if (!alive) return;
				setSrc(next.src);
				setFailed(false);
				timer = setTimeout(fetchNext, REFRESH_MS);
			};
			next.onerror = () => {
				if (!alive) return;
				setFailed(true);
				timer = setTimeout(fetchNext, REFRESH_MS * 3);
			};
			tick += 1;
			next.src = printerSnapshotUrl(printerId, camera.index, tick);
		};
		fetchNext();
		return () => {
			alive = false;
			if (timer) clearTimeout(timer);
		};
	}, [printerId, camera]);

	if (!camera) return null;
	return (
		<div className="printer-cam-box">
			{src && <img className="printer-cam" src={src} alt={`Camera: ${camera.name}`} />}
			{!src && <div className="printer-cam-empty">{failed ? 'The camera is not answering' : 'Waiting for the camera…'}</div>}
			<div className="printer-cam-bar">
				{cameras.length > 1 ? (
					<select aria-label="Camera" value={chosen} onChange={(e) => setChosen(Number(e.target.value))}>
						{cameras.map((c, i) => (
							<option key={c.index} value={i}>
								{c.name}
							</option>
						))}
					</select>
				) : (
					<span>Camera: {camera.name}</span>
				)}
			</div>
		</div>
	);
}
