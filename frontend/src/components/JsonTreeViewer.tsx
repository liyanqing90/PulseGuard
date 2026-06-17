import JsonView from "@uiw/react-json-view";

interface Props {
  value: object;
}

export function JsonTreeViewer({ value }: Props) {
  return <JsonView value={value} collapsed={2} displayDataTypes={false} shortenTextAfterLength={160} />;
}
