import PlaygroundShell from '@/features/iq-playground/engine/PlaygroundShell';
import zavaMedia from '@/features/iq-playground/scenarios/zava-media/scenario.json';
import type { Scenario } from '@/features/iq-playground/types/scenario';

const scenario = zavaMedia as unknown as Scenario;

export function IqInPracticePage() {
  return (
    <div className="iq-playground min-h-full flex-1">
      <PlaygroundShell scenario={scenario} />
    </div>
  );
}
