import type { Session } from "@supabase/supabase-js";
import { useEffect, useState } from "react";
import Login from "./app/Login";
import Shell from "./app/Shell";
import { supabase } from "./app/data";

export default function App() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);  // undefined while we check for a saved login

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);

  return (
    <div className="grape-bg h-full w-full overflow-hidden">
      <svg width="0" height="0" className="absolute" aria-hidden>
        <filter id="marker">{/* wobbly marker edge for the whiteboard frame */}
          <feTurbulence type="fractalNoise" baseFrequency="0.012 0.02" numOctaves="2" seed="7" />
          <feDisplacementMap in="SourceGraphic" scale="9" />
        </filter>
      </svg>
      {session === undefined ? null : session ? <Shell key={session.user.id} /> : <Login />}
    </div>
  );
}
