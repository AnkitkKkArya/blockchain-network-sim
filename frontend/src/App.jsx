import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Dashboard from "./pages/Dashboard";
import WalletPage from "./pages/Wallet";

const queryClient = new QueryClient();

const TABS = [
  { id: "dashboard", label: "Dashboard", Component: Dashboard },
  { id: "wallet", label: "Wallet", Component: WalletPage },
];

export default function App() {
  const [activeTab, setActiveTab] = useState("dashboard");
  const ActiveComponent = TABS.find((t) => t.id === activeTab).Component;

  return (
    <QueryClientProvider client={queryClient}>
      <div className="flex gap-1 bg-slate-950 px-6 pt-4">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium rounded-t-lg border-b-2 ${
              activeTab === tab.id
                ? "border-teal-500 text-teal-300"
                : "border-transparent text-slate-400 hover:text-slate-200"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <ActiveComponent />
    </QueryClientProvider>
  );
}
