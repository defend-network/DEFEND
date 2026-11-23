import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function AdminAccessDenied({ module }: { module: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Access denied</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm leading-6 text-slate-600">
          Your account does not have permission to view the {module} module.
          Contact the DEFEND owner if you believe this is an error.
        </p>
      </CardContent>
    </Card>
  );
}
