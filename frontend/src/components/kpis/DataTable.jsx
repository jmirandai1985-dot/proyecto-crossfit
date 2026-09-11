import React from 'react';

/**
 * Tabla simple.
 * @param {{key:string,label:string,render?:(value:any,row:any)=>React.ReactNode}[]} columns
 * @param {object[]} data
 */
export const DataTable = ({ columns, data = [] }) => {
    return (
        <div className="bg-zinc-900 rounded-lg shadow overflow-x-auto">
            <table className="w-full text-sm">
                <thead className="bg-zinc-800 border-b border-zinc-700">
                    <tr>
                        {columns.map((col) => (
                            <th key={col.key} className="px-6 py-3 text-left font-semibold text-gray-300 uppercase text-xs tracking-wider">
                                {col.label}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {data.length === 0 ? (
                        <tr>
                            <td colSpan={columns.length} className="px-6 py-4 text-center text-gray-400">
                                Sin datos
                            </td>
                        </tr>
                    ) : (
                        data.map((row, idx) => (
                            <tr key={idx} className="border-b border-zinc-800 hover:bg-zinc-800 transition">
                                {columns.map((col) => (
                                    <td key={col.key} className="px-6 py-4 text-gray-300">
                                        {col.render ? col.render(row[col.key], row) : row[col.key]}
                                    </td>
                                ))}
                            </tr>
                        ))
                    )}
                </tbody>
            </table>
        </div>
    );
};

export default DataTable;
