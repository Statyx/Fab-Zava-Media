import { getMode, MODE_LABEL, modeReason } from '@/data/mode';
import { statusChip, statusDot } from '@/domain/severity';

/**
 * Where the numbers come from, always on screen.
 *
 * The sister console made this a toggle because it carried a bundled data set to fall back
 * on. This one has none, so there is nothing to switch to — and a control that pretends
 * otherwise would promise a fallback that does not exist. It reads, and it explains itself on
 * hover; it does not act.
 */
export function ModeBadge() {
  const mode = getMode();
  const isLive = mode === 'live';

  return (
    <span
      title={modeReason()}
      className={[
        'flex items-center gap-2 rounded-md px-2.5 py-1 text-xs font-medium ring-1',
        isLive ? statusChip('ok') : statusChip('warn'),
      ].join(' ')}
    >
      <span
        aria-hidden="true"
        className={['h-1.5 w-1.5 rounded-full', statusDot(isLive ? 'ok' : 'warn')].join(' ')}
      />
      {MODE_LABEL[mode]}
    </span>
  );
}
