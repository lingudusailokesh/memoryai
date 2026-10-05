export default function Placeholder({ title, stage }: { title: string; stage: number }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-2 text-mute">Not built yet. Planned for Stage {stage}.</p>
    </div>
  );
}
