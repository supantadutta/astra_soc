"use client";

import { useMemo } from "react";
import ReactFlow, { Background, Controls, Edge, Node, MarkerType } from "reactflow";
import "reactflow/dist/style.css";

const KIND_COLOR: Record<string, string> = {
  user: "#22d3ee", account: "#22d3ee", host: "#a78bfa", ip: "#f59e0b",
  domain: "#f43f5e", file: "#2dd4bf", process: "#60a5fa", vulnerability: "#f43f5e",
  cloud_resource: "#34d399", mailbox: "#22d3ee",
};

export function EntityGraph({
  nodes,
  edges,
  height = 420,
}: {
  nodes: { id: string; label: string; kind: string; risk?: number; criticality?: string }[];
  edges: { source: string; target: string; type: string }[];
  height?: number;
}) {
  const flowNodes: Node[] = useMemo(() => {
    const R = 180;
    const cx = 300, cy = height / 2;
    return nodes.map((n, i) => {
      const angle = (i / Math.max(1, nodes.length)) * Math.PI * 2;
      const color = KIND_COLOR[n.kind] || "#22d3ee";
      return {
        id: n.id,
        position: { x: cx + R * Math.cos(angle) + (i % 2) * 40, y: cy + R * Math.sin(angle) },
        data: { label: `${n.label}` },
        style: {
          background: "rgba(13,21,38,0.95)",
          border: `1.5px solid ${color}`,
          color: "#e6f0ff",
          borderRadius: 10,
          fontSize: 11,
          padding: "6px 10px",
          maxWidth: 170,
          boxShadow: (n.criticality === "critical" || n.criticality === "high")
            ? `0 0 16px -2px ${color}` : "none",
        },
      };
    });
  }, [nodes, height]);

  const flowEdges: Edge[] = useMemo(
    () =>
      edges.map((e, i) => ({
        id: `e${i}`,
        source: e.source,
        target: e.target,
        label: e.type.replace(/_/g, " "),
        animated: true,
        style: { stroke: "#22d3ee66" },
        labelStyle: { fill: "#6f83a6", fontSize: 9 },
        labelBgStyle: { fill: "#0a0f1c" },
        markerEnd: { type: MarkerType.ArrowClosed, color: "#22d3ee88" },
      })),
    [edges]
  );

  if (!nodes.length)
    return <div className="text-ink-500 text-sm py-16 text-center">No entity relationships to display.</div>;

  return (
    <div style={{ height }} className="rounded-lg overflow-hidden border border-white/5">
      <ReactFlow nodes={flowNodes} edges={flowEdges} fitView proOptions={{ hideAttribution: true }}
        nodesDraggable nodesConnectable={false} elementsSelectable>
        <Background color="#1d3352" gap={22} />
        <Controls className="!bg-navy-800 !border-white/10" showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
