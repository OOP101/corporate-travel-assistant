export interface SkeletonProps {
  className?: string;
  width?: string;
  height?: string;
}

export const Skeleton = ({ className, width, height }: SkeletonProps) => (
  <div className={`skeleton ${className || ''}`} style={{ width, height }} />
);

/** 卡片区域的占位骨架：用于首屏加载，避免页面跳动 */
export const SkeletonCards = ({ count = 3, height = 96 }: { count?: number; height?: number }) => (
  <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
    {Array.from({ length: count }).map((_, i) => (
      <div key={i} className="skeleton" style={{ height }} />
    ))}
  </div>
);

/** 段落骨架 */
export const SkeletonLines = ({ lines = 4 }: { lines?: number }) => (
  <div className="space-y-2.5">
    {Array.from({ length: lines }).map((_, i) => (
      <div key={i} className="skeleton h-3.5" style={{ width: i === lines - 1 ? '60%' : '100%' }} />
    ))}
  </div>
);
