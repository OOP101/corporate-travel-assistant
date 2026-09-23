import { ReactNode } from 'react';

export interface Column<T> {
  key: string;
  title: string;
  width?: string;
  align?: 'left' | 'right' | 'center';
  render?: (row: T, index: number) => ReactNode;
}

export interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  loading?: boolean;
  skeletonRows?: number;
  empty?: ReactNode;
  className?: string;
}

const alignCls = (a?: string) =>
  a === 'right' ? 'text-right' : a === 'center' ? 'text-center' : 'text-left';

/**
 * 数据表格：管理台的主力展示形态。
 * 统一了表头样式、行悬停、加载骨架与空态，避免各页面自己拼 <table>。
 */
export function Table<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  loading,
  skeletonRows = 5,
  empty,
  className,
}: TableProps<T>) {
  if (loading) {
    return (
      <div className={className}>
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={alignCls(c.align)} style={{ width: c.width }}>
                  {c.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: skeletonRows }).map((_, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c.key} className={alignCls(c.align)}>
                    <div className="skeleton h-3.5" />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (!rows.length && empty) return <>{empty}</>;

  return (
    <div className={className}>
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={alignCls(c.align)} style={{ width: c.width }}>
                {c.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={rowKey(row, i)}
              className={onRowClick ? 'is-clickable' : ''}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((c) => (
                <td key={c.key} className={alignCls(c.align)}>
                  {c.render ? c.render(row, i) : ((row as any)[c.key] ?? '-')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
