import Link from "next/link";

export default function NotFound() {
  return (
    <main className="relative z-[1] grid min-h-[70vh] place-items-center px-4">
      <div className="max-w-[460px] text-center">
        <p className="m-0 font-mono text-[13px] text-ash">404</p>
        <h1 className="display m-0 text-[24px]">Page not found</h1>
        <p className="text-[14.5px] text-ash">The page you asked for does not exist, or you do not have access to it.</p>
        <Link href="/" className="display inline-block rounded-[var(--radius)] border px-4 py-2 text-[13px] no-underline"
              style={{ background: "var(--grad-primary)", borderColor: "transparent", color: "var(--on-accent)" }}>Go to my home page</Link>
      </div>
    </main>
  );
}
