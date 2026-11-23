export function cmsWritePermission(input: {
  publish?: boolean;
  visibility?: string;
}): "cms.edit" | "cms.publish" {
  if (input.publish) return "cms.publish";
  if (input.visibility && input.visibility !== "admin") return "cms.publish";
  return "cms.edit";
}
