import { Link } from "react-router";
import { Card, CardBody } from "../components/ui/Card";

export function NotFoundPage() {
  return (
    <Card className="mx-auto max-w-lg text-center">
      <CardBody className="py-10">
        <p className="font-mono text-sm text-slate-400">404</p>
        <h1 className="mt-2 text-xl font-semibold text-slate-900">Page not found</h1>
        <p className="mt-2 text-sm text-slate-600">This area of Carbon Copy has not been built yet.</p>
        <Link to="/" className="mt-6 inline-block text-sm font-medium text-brand-700 hover:underline">
          Back to overview
        </Link>
      </CardBody>
    </Card>
  );
}
