import { useEffect, useState, type ReactNode } from "react";

import { Icon } from "../components/Icon";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "./Accordion";
import { Alert } from "./Alert";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "./Card";
import { Checkbox } from "./Checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "./Collapsible";
import { Command } from "./Command";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./Dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuShortcut,
  DropdownMenuTrigger,
} from "./DropdownMenu";
import { EmptyState } from "./EmptyState";
import { Input } from "./Input";
import { Item } from "./Item";
import { Kbd } from "./Kbd";
import { Popover, PopoverContent, PopoverTrigger } from "./Popover";
import { Progress } from "./Progress";
import { RadioGroup, RadioGroupItem } from "./RadioGroup";
import { ScrollArea } from "./ScrollArea";
import { Select } from "./Select";
import { Separator } from "./Separator";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from "./Sheet";
import { Skeleton, SkeletonRows } from "./Skeleton";
import { Switch } from "./Switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./Table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./Tabs";
import { Textarea } from "./Textarea";
import { Toast, ToastViewport } from "./Toast";
import { ToggleGroup, ToggleGroupItem } from "./ToggleGroup";
import { Tooltip } from "./Tooltip";

function paint(theme: "light" | "dark") {
  document.documentElement.dataset.theme = theme;
}

export function KitGallery() {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("theme");
    const next = q === "dark" ? "dark" : "light";
    setTheme(next);
    paint(next);
  }, []);

  const set = (next: "light" | "dark") => {
    setTheme(next);
    paint(next);
  };

  return (
    <div className="kit-gallery" data-testid="kit-gallery" data-theme={theme}>
      <header className="kit-head">
        <div>
          <p className="kit-kicker">Rigorloom kit</p>
          <h1>Primitives</h1>
        </div>
        <ToggleGroup value={theme} onValueChange={(v) => set(v as "light" | "dark")} aria-label="테마">
          <ToggleGroupItem value="light">라이트</ToggleGroupItem>
          <ToggleGroupItem value="dark">다크</ToggleGroupItem>
        </ToggleGroup>
      </header>

      <Section title="Button">
        <div className="kit-row">
          {(["primary", "secondary", "ghost", "destructive", "link"] as const).map((v) => (
            <Button key={v} variant={v}>
              {v}
            </Button>
          ))}
        </div>
        <div className="kit-row">
          <Button size="sm">sm</Button>
          <Button size="md">md</Button>
          <Button loading>loading</Button>
          <Button disabled>disabled</Button>
        </div>
      </Section>

      <Section title="Input / Textarea / Select">
        <div className="kit-row">
          <Input placeholder="이름" defaultValue="김가상" aria-label="이름" />
          <Input placeholder="비활성" disabled aria-label="비활성" />
          <Select defaultValue="xml" aria-label="백엔드">
            <option value="xml">xml</option>
            <option value="native">native</option>
          </Select>
        </div>
        <Textarea defaultValue="메모" aria-label="메모" />
      </Section>

      <Section title="Switch / Checkbox / Radio / Toggle">
        <div className="kit-row">
          <Switch aria-label="알림" />
          <Switch defaultChecked aria-label="알림 켜짐" />
          <Checkbox>안내 표시</Checkbox>
          <Checkbox defaultChecked>채움 칸</Checkbox>
        </div>
        <RadioGroup defaultValue="xml" aria-label="엔진">
          <RadioGroupItem value="xml">xml</RadioGroupItem>
          <RadioGroupItem value="native">native</RadioGroupItem>
        </RadioGroup>
        <ToggleGroup defaultValue="document" aria-label="보기">
          <ToggleGroupItem value="document">문서</ToggleGroupItem>
          <ToggleGroupItem value="agent">에이전트</ToggleGroupItem>
        </ToggleGroup>
      </Section>

      <Section title="Tabs">
        <Tabs defaultValue="one">
          <TabsList>
            <TabsTrigger value="one">선택</TabsTrigger>
            <TabsTrigger value="two">검토</TabsTrigger>
            <TabsTrigger value="three">기록</TabsTrigger>
          </TabsList>
          <TabsContent value="one">선택 패널</TabsContent>
          <TabsContent value="two">검토 패널</TabsContent>
          <TabsContent value="three">기록 패널</TabsContent>
        </Tabs>
      </Section>

      <Section title="Tooltip / Popover / Menu">
        <div className="kit-row kit-layers">
          <Tooltip content="홈으로" open disablePortal>
            <button type="button" className="ui-btn ui-btn-secondary ui-btn-md">
              홈
            </button>
          </Tooltip>
          <Popover open disablePortal>
            <PopoverTrigger>자세히</PopoverTrigger>
            <PopoverContent>
              <p>검사 엔진 xml · 구조만 확인합니다.</p>
            </PopoverContent>
          </Popover>
          <DropdownMenu open disablePortal>
            <DropdownMenuTrigger>열기 ▾</DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuLabel>문서</DropdownMenuLabel>
              <DropdownMenuItem>
                열기
                <DropdownMenuShortcut>Ctrl+O</DropdownMenuShortcut>
              </DropdownMenuItem>
              <DropdownMenuItem>양식과 함께 열기</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem>저장/내보내기</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </Section>

      <Section title="Dialog / Sheet">
        <div className="kit-previews">
          <div className="kit-preview">
            <Dialog open disablePortal>
              <DialogTrigger>대화상자</DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>적용할까요?</DialogTitle>
                  <DialogDescription>후보본을 만들고 기록을 남깁니다.</DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <DialogClose>취소</DialogClose>
                  <Button variant="primary">적용</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
          <div className="kit-preview">
            <Sheet open disablePortal side="right">
              <SheetTrigger>시트</SheetTrigger>
              <SheetContent>
                <SheetHeader>
                  <SheetTitle>설정</SheetTitle>
                  <SheetClose />
                </SheetHeader>
                <SheetDescription>제공자와 테마.</SheetDescription>
                <p className="kit-note">오른쪽 패널 · width token</p>
              </SheetContent>
            </Sheet>
          </div>
        </div>
      </Section>

      <Section title="Collapsible / Accordion">
        <Collapsible defaultOpen>
          <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
          <CollapsibleContent>
            <p className="kit-note">table 0 · row 0 · col 14</p>
          </CollapsibleContent>
        </Collapsible>
        <Accordion type="single" defaultValue="a">
          <AccordionItem value="a">
            <AccordionTrigger>영수증</AccordionTrigger>
            <AccordionContent>해시와 검사가 여기 있습니다.</AccordionContent>
          </AccordionItem>
          <AccordionItem value="b">
            <AccordionTrigger>비교</AccordionTrigger>
            <AccordionContent>이전 후보본과 맞춥니다.</AccordionContent>
          </AccordionItem>
        </Accordion>
      </Section>

      <Section title="Badge / Kbd / Separator">
        <div className="kit-row">
          <Badge>default</Badge>
          <Badge variant="secondary">secondary</Badge>
          <Badge variant="outline">outline</Badge>
          <Badge variant="success">success</Badge>
          <Badge variant="warning">warning</Badge>
          <Badge variant="destructive">destructive</Badge>
          <Kbd>Ctrl+K</Kbd>
        </div>
        <Separator />
        <div className="kit-row" style={{ height: 32 }}>
          <span>가로</span>
          <Separator orientation="vertical" />
          <span>세로</span>
        </div>
      </Section>

      <Section title="ScrollArea / Progress / Alert">
        <ScrollArea className="kit-scroll">
          {Array.from({ length: 12 }, (_, i) => (
            <p key={i} className="kit-note">
              줄 {i + 1}
            </p>
          ))}
        </ScrollArea>
        <Progress value={64} aria-label="채움" />
        <Progress aria-label="진행 중" />
        <Alert variant="info" title="안내" icon={<Icon name="list" />}>
          구조만 확인한 결과입니다.
        </Alert>
        <Alert variant="warning" title="주의" icon={<Icon name="warn" />}>
          원본은 건드리지 않았습니다.
        </Alert>
        <Alert variant="destructive" title="실패" icon={<Icon name="x" />}>
          런타임을 시작하지 못했습니다.
        </Alert>
      </Section>

      <Section title="Table / Card / Item">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>칸</TableHead>
              <TableHead>값</TableHead>
              <TableHead>검사</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>표 1 · 1행 15열</TableCell>
              <TableCell>행정안전부</TableCell>
              <TableCell>통과</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>표 1 · 2행 1열</TableCell>
              <TableCell>—</TableCell>
              <TableCell>대기</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <Card>
          <CardHeader>
            <CardTitle>계획</CardTitle>
            <CardDescription>한 칸을 채웁니다.</CardDescription>
          </CardHeader>
          <CardContent>fill_cell · 표 1 · 1행 15열</CardContent>
          <CardFooter>
            <Button variant="primary" size="sm">
              승인
            </Button>
          </CardFooter>
        </Card>
        <Item
          icon={<Icon name="open" />}
          title="gianmun-byeolji-1ho.hwpx"
          description="어제 열림"
          trailing={<Badge variant="outline">hwpx</Badge>}
          active
        />
        <Item
          icon={<Icon name="history" />}
          title="gone.hwpx"
          description="없음"
          trailing={<Badge variant="warning">missing</Badge>}
        />
      </Section>

      <Section title="Skeleton / Toast / Empty / Command">
        <Skeleton className="ui-skeleton-block" />
        <SkeletonRows rows={3} />
        <ToastViewport className="kit-toasts">
          <Toast>적용했습니다</Toast>
          <Toast variant="success">검사 통과</Toast>
          <Toast variant="destructive" action={<Button variant="ghost" size="sm">다시</Button>}>
            실패
          </Toast>
        </ToastViewport>
        <EmptyState
          icon={<Icon name="list" size={20} />}
          title="검토할 것이 없습니다"
          body="문서에서 칸을 고르면 여기 쌓입니다."
          action={{ label: "열기", onClick: () => undefined }}
        />
        <Command
          items={[
            { id: "open", label: "열기", shortcut: "Ctrl+O" },
            { id: "check", label: "검사" },
            { id: "home", label: "홈", shortcut: "Ctrl+Shift+H" },
          ]}
        />
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="kit-section">
      <h2>{title}</h2>
      <div className="kit-section-body">{children}</div>
    </section>
  );
}
