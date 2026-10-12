import type { AppCtx } from '../hooks/useAppController';

export default function MainLineUpDialog({ c }: { c: AppCtx }) {
	const { needsLineUpQuestion, currentJob, setLineUpAnsweredFor, setBeltLineUp, setRetryAfterLineUp } = c;
	return (
		<>
			{needsLineUpQuestion && currentJob && (
				<div className="confirm-backdrop" role="alertdialog" aria-modal="true" aria-label="Line the objects up along the belt?">
					<div className="confirm-dialog">
						<p>
							These objects don&rsquo;t fit side by side when the slicer arranges them on the belt bed. Slice them lined up along the belt
							instead?
						</p>
						<div className="confirm-actions">
							<button type="button" className="toast-dismiss" onClick={() => setLineUpAnsweredFor(currentJob.id)}>
								Cancel
							</button>
							<button
								type="button"
								onClick={() => {
									setLineUpAnsweredFor(currentJob.id);
									setBeltLineUp(true);
									setRetryAfterLineUp(true);
								}}
							>
								Line them up and slice
							</button>
						</div>
					</div>
				</div>
			)}
		</>
	);
}
