export function fieldProps(id: string, message: string | undefined) {
  return message
    ? { "aria-invalid": true as const, "aria-describedby": `${id}-error` }
    : {};
}

export function FieldError({
  id,
  message,
}: {
  id: string;
  message: string | undefined;
}) {
  if (!message) return null;
  return (
    <span className="field-error" id={`${id}-error`}>
      {message}
    </span>
  );
}
