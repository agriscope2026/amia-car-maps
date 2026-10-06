import { promises as fs } from "fs";
import path from "path";
import { notFound, redirect } from "next/navigation";
import { currentUser } from "@/lib/server/auth";
import { PRODUCT_TYPES, type Gazetteer, type ProductType } from "@/lib/types";
import { AdminBar } from "../../AdminBar";
import UploadWizard from "@/components/admin/UploadWizard";

export const dynamic = "force-dynamic";

export default async function NewProduct({ params }: { params: Promise<{ type: string }> }) {
  const user = await currentUser();
  if (!user) redirect("/admin/login");
  const type = (await params).type as ProductType;
  if (!PRODUCT_TYPES.some((t) => t.id === type)) notFound();
  const geo = JSON.parse(await fs.readFile(path.join(process.cwd(), "public", "geo", "car.json"), "utf-8")) as Gazetteer;
  return (
    <>
      <AdminBar email={user.email} role={user.role} />
      <UploadWizard type={type} geo={geo} />
    </>
  );
}
