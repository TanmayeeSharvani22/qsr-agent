// SPDX-FileCopyrightText: (C) 2026 Intel Corporation
// SPDX-License-Identifier: Apache-2.0

import { PanelLeft } from "lucide-react";
import { useState } from "react";
import { AutonomyPanel } from "@/components/autonomy/AutonomyPanel";
import { ChatPanel } from "@/components/chat/ChatPanel";
import { AppFooter } from "@/components/layout/AppFooter";
import { AppHeader } from "@/components/layout/AppHeader";
import { ServicesPanel } from "@/components/services/ServicesPanel";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Toaster } from "@/components/ui/sonner";
import { useChat } from "@/hooks/use-chat";
import { useAutonomy } from "@/hooks/use-autonomy";
import { useServices } from "@/hooks/use-services";

export default function App() {
  const services = useServices();
  const chat = useChat();
  const autonomy = useAutonomy(chat.addError);
  const [sheetOpen, setSheetOpen] = useState(false);

  const refreshAll = () => {
    void services.refresh();
    void autonomy.refresh();
  };
  const panel = (
    <ServicesPanel phase={services.phase} servers={services.servers} statuses={services.statuses} error={services.error} onRefresh={refreshAll} />
  );

  return (
    <div className="flex h-dvh flex-col bg-background text-foreground">
      <a href="#chat-title" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded-md focus:bg-primary focus:px-3 focus:py-2 focus:text-primary-foreground">
        Skip to chat
      </a>
      <AppHeader
        servicesTrigger={
          <Button variant="outline" size="sm" className="md:hidden" onClick={() => setSheetOpen(true)} aria-label="Open services">
            <PanelLeft aria-hidden /> Services
          </Button>
        }
      />
      <main className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto md:grid-cols-[220px_minmax(0,1fr)_300px] md:overflow-hidden lg:grid-cols-[280px_minmax(0,1fr)_350px]">
        <aside aria-label="Services" className="hidden min-h-0 border-r bg-card md:block">{panel}</aside>
        <div className="flex min-h-[28rem] min-w-0 flex-col md:min-h-0">
          <ChatPanel messages={chat.messages} status={chat.status} send={chat.send} />
        </div>
        <aside aria-label="Autonomy" className="min-h-[16rem] border-t bg-card md:min-h-0 md:border-t-0 md:border-l">
          <AutonomyPanel data={autonomy.data} phase={autonomy.phase} error={autonomy.error} fetchedAt={autonomy.fetchedAt} busy={autonomy.busy} onDecide={(id, d) => void autonomy.decide(id, d)} />
        </aside>
      </main>
      <AppFooter />
      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side="left">
          <SheetHeader>
            <SheetTitle>Services</SheetTitle>
            <SheetDescription className="sr-only">MCP service status</SheetDescription>
          </SheetHeader>
          {panel}
        </SheetContent>
      </Sheet>
      <Toaster position="bottom-right" />
    </div>
  );
}
