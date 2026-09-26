import { Eye, EyeOff, LogIn, Search } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";
import { EMAIL_DOMAIN, colorFor, publicApi, supabase, type Company } from "./data";
import { beaver } from "./mascot";

const Beaver = lazy(() => import("./Beaver"));

const DEMO_PASSWORD = "crewly123";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [people, setPeople] = useState<Company[]>([]);
  const [q, setQ] = useState("");

  useEffect(() => { publicApi.get<Company[]>("/api/app/directory").then(setPeople).catch(() => setPeople([])); }, []);
  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return people.filter((c) => !t || [c.name, c.short, c.state ?? "", c.login ?? ""].some((x) => x.toLowerCase().includes(t)));
  }, [people, q]);

  const submit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const name = username.trim().toLowerCase();
    if (!name || !password) { setError("Enter your username and password."); beaver("sad"); return; }
    setBusy(true); setError(null); beaver("thinking");
    const { error } = await supabase.auth.signInWithPassword({ email: name.includes("@") ? name : `${name}@${EMAIL_DOMAIN}`, password });
    setBusy(false);
    if (error) { setError("That username and password don't match. Try one of the demo logins below."); beaver("sad"); }
    else beaver("happy");
  };

  return (
    <main className="flex h-full w-full items-center justify-center p-8">
      <div className="board pop-in flex w-full max-w-[880px] items-stretch gap-2 p-8 md:p-10">
        <div className="board-frame" />
        <div className="relative hidden w-[300px] shrink-0 md:block">
          <Suspense fallback={null}><Beaver className="absolute -bottom-6 -left-6 h-[360px] w-[330px]" /></Suspense>
        </div>
        <form onSubmit={submit} className="flex flex-1 flex-col gap-5 md:pl-6">
          <div>
            <div className="font-logo text-5xl font-semibold tracking-tight text-grape">crewly</div>
            <p className="mt-2 text-muted">Find where your projects overlap with the utility next door, and build together.</p>
          </div>

          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-semibold">Username</span>
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username"
              onFocus={() => beaver("nod")} placeholder="dominion or georgia"
              className="pen-box bg-white px-4 py-3 outline-none placeholder:text-faint focus:bg-grape-soft/40" />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-semibold">Password</span>
            <div className="pen-box flex items-center bg-white pr-2 focus-within:bg-grape-soft/40">
              <input value={password} onChange={(e) => setPassword(e.target.value)} type={show ? "text" : "password"} autoComplete="current-password"
                className="min-w-0 flex-1 bg-transparent px-4 py-3 outline-none" />
              <button type="button" onClick={() => setShow(!show)} className="rounded-full p-2 text-muted hover:text-ink" aria-label={show ? "Hide password" : "Show password"}>
                {show ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </label>

          {error && <p className="pop-in -mt-1 text-sm font-medium text-warn" role="alert">{error}</p>}

          <button disabled={busy} className="pen-btn flex items-center justify-center gap-2 bg-grape px-6 py-3 font-logo text-lg font-semibold text-white">
            <LogIn size={19} /> {busy ? "Logging in..." : "Log in"}
          </button>

          <div className="mt-1 border-t-2 border-dashed border-line pt-4">
            <div className="mb-2 flex items-center gap-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-faint">Demo logins</span>
              <span className="text-xs text-faint">{people.length ? `${people.length} utilities` : ""}</span>
            </div>
            {people.length > 4 && (
              <div className="mb-2 flex items-center gap-2 rounded-full border-2 border-line bg-white px-3 py-1.5 focus-within:border-pen">
                <Search size={15} className="text-faint" />
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a utility, state or username" aria-label="Find a utility"
                  className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-faint" />
              </div>
            )}
            <div className="thin-scroll -mr-1 flex max-h-44 flex-col gap-1 overflow-y-auto pr-1">
              {shown.map((c) => (
                <button key={c.id} type="button" onClick={() => { setUsername(c.login!); setPassword(DEMO_PASSWORD); setError(null); beaver("wave"); }}
                  className={`flex items-center gap-2.5 rounded-2xl border-2 px-3 py-1.5 text-left text-sm hover:border-ink ${username === c.login ? "border-pen bg-grape-soft" : "border-line bg-white"}`}>
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: c.color || colorFor(c.id) }} />
                  <span className="min-w-0 flex-1 truncate font-semibold">{c.name}</span>
                  {c.state && <span className="shrink-0 rounded-full bg-soft px-1.5 text-xs font-semibold text-muted">{c.state}</span>}
                  <span className="shrink-0 text-muted">{c.login} / {DEMO_PASSWORD}</span>
                </button>
              ))}
              {people.length > 0 && !shown.length && <p className="px-2 py-2 text-sm text-muted">No utility matches.</p>}
            </div>
          </div>
        </form>
      </div>
    </main>
  );
}
