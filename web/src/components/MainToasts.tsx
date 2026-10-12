import type { AppCtx } from '../hooks/useAppController';

export default function MainToasts({ c }: { c: AppCtx }) {
	const {
		meshReport,
		meshToastDismissed,
		setMeshToastDismissed,
		showScaleToast,
		fitDimensions,
		bedSize,
		fitScale,
		printerName,
		handleAcceptScaleToFit,
		scaling,
		setScaleToastDismissed,
	} = c;
	return (
		<>
			{meshReport && !meshToastDismissed && (
				<div className="toast toast-top" role="status">
					<div className="toast-message">
						{meshReport.fixed.length > 0 && (
							<p>
								<strong>Auto-fixed a non-manifold file.</strong> {meshReport.fixed.join('; ')}.
							</p>
						)}
						{meshReport.warnings.map((w) => (
							<p key={w}>{w}</p>
						))}
					</div>
					<div className="toast-actions">
						<button type="button" className="toast-dismiss" onClick={() => setMeshToastDismissed(true)}>
							Dismiss
						</button>
					</div>
				</div>
			)}
			{showScaleToast && fitDimensions && bedSize && fitScale !== null && (
				<div className="toast">
					<div className="toast-message">
						This model ({fitDimensions.x.toFixed(0)} × {fitDimensions.y.toFixed(0)} × {fitDimensions.z.toFixed(0)} mm) is larger than{' '}
						{printerName}&rsquo;s build volume ({bedSize.width.toFixed(0)} × {bedSize.depth.toFixed(0)} × {bedSize.height.toFixed(0)} mm).
						Scale it down to {Math.round(fitScale * 100)}% to fit?
					</div>
					<div className="toast-actions">
						<button type="button" onClick={handleAcceptScaleToFit} disabled={scaling}>
							{scaling ? 'Scaling…' : 'Scale to fit'}
						</button>
						<button type="button" className="toast-dismiss" onClick={() => setScaleToastDismissed(true)} disabled={scaling}>
							Dismiss
						</button>
					</div>
				</div>
			)}
		</>
	);
}
