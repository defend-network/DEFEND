"use client";

type Props = { href?: string };

export function Brand({ href = "/" }: Props) {
  const inner = (
    <>
      <div className="brand-mark">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/defend-logo.png" alt="DEFEND" width={80} height={42} />
      </div>
      <div className="brand-copy">
        <strong>DEFEND AI</strong>
        <span>For European-heritage Americans</span>
      </div>
    </>
  );

  if (href) {
    return (
      <a className="brand" href={href} title="Home">
        {inner}
      </a>
    );
  }
  return <div className="brand">{inner}</div>;
}
