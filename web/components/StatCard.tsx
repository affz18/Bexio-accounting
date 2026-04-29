import { cn } from "@/lib/utils";

interface StatCardProps {
  label: string;
  value: string | number;
  sublabel?: string;
  trend?: "up" | "down" | "flat";
  className?: string;
}

export function StatCard({ label, value, sublabel, trend, className }: StatCardProps) {
  return (
    <div className={cn("card p-6", className)}>
      <div className="text-sm text-foreground-muted">{label}</div>
      <div className="mt-2 text-3xl font-semibold tracking-tight">{value}</div>
      {sublabel && (
        <div className={cn(
          "mt-1 text-xs",
          trend === "up" && "text-success",
          trend === "down" && "text-danger",
          (!trend || trend === "flat") && "text-foreground-muted",
        )}>
          {sublabel}
        </div>
      )}
    </div>
  );
}
