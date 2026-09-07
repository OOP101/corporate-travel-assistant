import { useState, useEffect } from 'react';
import {
  Building2, Users, Plus, Edit2, Trash2, Search, UserPlus,
} from 'lucide-react';
import {
  listDepartments, createDepartment, updateDepartment, deleteDepartment,
  listEmployees, createEmployee, updateEmployee, deleteEmployee,
} from '../api/organization';
import {
  Button, Input, Select, Tab, ModalForm, Card, EmptyState, PageHeader,
} from '../components';
import LEVEL_OPTIONS from '../components/Atoms/level-options';

const getLevelLabel = (level) => LEVEL_OPTIONS.find((l) => l.value === level)?.label || level || '-';

export default function OrgPage() {
  const [activeTab, setActiveTab] = useState('departments');
  const [departments, setDepartments] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [modalType, setModalType] = useState('department');
  const [editingItem, setEditingItem] = useState(null);
  const [searchKeyword, setSearchKeyword] = useState('');

  const loadData = async () => {
    setLoading(true);
    try {
      if (activeTab === 'departments') {
        const res = await listDepartments();
        setDepartments(res.departments || []);
      } else {
        const res = await listEmployees();
        setEmployees(res.employees || []);
      }
    } catch (err) {
      console.error('加载数据失败:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, [activeTab]);

  const handleCreate = (type) => {
    setModalType(type);
    setEditingItem(null);
    setShowModal(true);
  };

  const handleEdit = (item, type) => {
    setModalType(type);
    setEditingItem(item);
    setShowModal(true);
  };

  const handleDelete = async (id, type) => {
    if (!confirm('确定删除吗？')) return;
    try {
      if (type === 'department') await deleteDepartment(id);
      else await deleteEmployee(id);
      loadData();
    } catch (err) {
      console.error('删除失败:', err);
    }
  };

  const getDeptName = (deptId) => departments.find((d) => d.dept_id === deptId)?.name || deptId || '-';

  const filteredEmployees = employees.filter((emp) =>
    !searchKeyword ||
    emp.name?.includes(searchKeyword) ||
    emp.title?.includes(searchKeyword) ||
    emp.email?.includes(searchKeyword)
  );

  const modalFields = modalType === 'department'
    ? [
        { name: 'name', label: '部门名称', type: 'text', placeholder: '请输入部门名称', rule: { required: true, message: '必填项' } },
        { name: 'description', label: '描述', type: 'textarea', placeholder: '部门描述（可选）' },
        { name: 'parent_id', label: '上级部门', type: 'select', options: departments.map((d) => ({ value: d.dept_id, label: d.name })), placeholder: '请选择' },
        { name: 'manager_id', label: '部门主管', type: 'text', placeholder: '主管姓名' },
      ]
    : [
        { name: 'name', label: '姓名', type: 'text', placeholder: '请输入员工姓名', rule: { required: true, message: '必填项' } },
        { name: 'dept_id', label: '所属部门', type: 'select', options: departments.map((d) => ({ value: d.dept_id, label: d.name })), placeholder: '请选择部门' },
        { name: 'level', label: '职级', type: 'select', options: LEVEL_OPTIONS.map((o) => ({ value: o.value, label: o.label })), placeholder: '选择职级' },
        { name: 'title', label: '职位', type: 'text', placeholder: '职位名称' },
        { name: 'email', label: '邮箱', type: 'text', placeholder: '员工邮箱' },
      ];

  return (
    <div className="h-full flex flex-col px-6 py-5">
      <PageHeader
        title="组织管理"
        subtitle="维护部门架构与员工信息，支撑差旅政策与审批"
      />

      <div className="flex-1 overflow-y-auto -mx-6 px-6 pb-4">
        <div className="max-w-5xl mx-auto space-y-4">
          <Tab
            tabs={[
              { label: '部门管理', value: 'departments' },
              { label: '员工管理', value: 'employees' },
            ]}
            defaultActive="departments"
            onChange={setActiveTab}
          />

          {activeTab === 'departments' ? (
            <Card>
              <div className="mb-4">
                <Button onClick={() => handleCreate('department')}>
                  <Plus size={15} /> 新建部门
                </Button>
              </div>

              {loading ? (
                <EmptyState icon={<Building2 size={22} />} title="加载中..." />
              ) : departments.length === 0 ? (
                <EmptyState
                  icon={<Building2 size={22} />}
                  title="暂无部门数据"
                  action={{ label: '创建第一个部门', onClick: () => handleCreate('department') }}
                />
              ) : (
                <div className="overflow-x-auto -mx-5 px-5">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-ink-400 border-b border-gray-100">
                        <th className="py-3 pr-4 font-medium">部门名称</th>
                        <th className="py-3 pr-4 font-medium">描述</th>
                        <th className="py-3 pr-4 font-medium">上级部门</th>
                        <th className="py-3 pr-4 font-medium">创建时间</th>
                        <th className="py-3 text-right font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {departments.map((dept) => (
                        <tr key={dept.dept_id} className="hover:bg-gray-50/60 transition-colors">
                          <td className="py-3 pr-4">
                            <div className="flex items-center gap-2.5">
                              <span className="w-8 h-8 rounded-lg bg-primary-50 text-primary-600 flex items-center justify-center">
                                <Building2 size={15} />
                              </span>
                              <span className="font-medium text-ink-900">{dept.name}</span>
                            </div>
                          </td>
                          <td className="py-3 pr-4 text-ink-600">{dept.description || '-'}</td>
                          <td className="py-3 pr-4 text-ink-600">{dept.parent_id ? getDeptName(dept.parent_id) : '-'}</td>
                          <td className="py-3 pr-4 text-ink-400">{dept.created_at ? new Date(dept.created_at * 1000).toLocaleDateString() : '-'}</td>
                          <td className="py-3 text-right whitespace-nowrap">
                            <Button size="sm" type="ghost" onClick={() => handleEdit(dept, 'department')}><Edit2 size={13} /></Button>
                            <Button size="sm" type="ghost" className="text-red-500! hover:bg-red-50!" onClick={() => handleDelete(dept.dept_id, 'department')}><Trash2 size={13} /></Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          ) : (
            <Card>
              <div className="flex items-center gap-2.5 mb-4">
                <div className="relative flex-1 max-w-xs">
                  <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400" />
                  <Input
                    type="text"
                    placeholder="搜索员工姓名/职位..."
                    value={searchKeyword}
                    onChange={(v) => setSearchKeyword(String(v))}
                    className="pl-9!"
                  />
                </div>
                <Button type="secondary" onClick={() => handleCreate('employee')}>
                  <UserPlus size={15} /> 添加员工
                </Button>
              </div>

              {loading ? (
                <EmptyState icon={<Users size={22} />} title="加载中..." />
              ) : filteredEmployees.length === 0 ? (
                <EmptyState
                  icon={<Users size={22} />}
                  title={searchKeyword ? '未找到匹配的员工' : '暂无员工数据'}
                />
              ) : (
                <div className="overflow-x-auto -mx-5 px-5">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-ink-400 border-b border-gray-100">
                        <th className="py-3 pr-4 font-medium">姓名</th>
                        <th className="py-3 pr-4 font-medium">职位</th>
                        <th className="py-3 pr-4 font-medium">部门</th>
                        <th className="py-3 pr-4 font-medium">职级</th>
                        <th className="py-3 pr-4 font-medium">邮箱</th>
                        <th className="py-3 text-right font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-50">
                      {filteredEmployees.map((emp) => (
                        <tr key={emp.employee_id} className="hover:bg-gray-50/60 transition-colors">
                          <td className="py-3 pr-4">
                            <div className="flex items-center gap-2.5">
                              <div className="w-8 h-8 rounded-full bg-primary-50 text-primary-600 flex items-center justify-center text-sm font-medium">
                                {emp.name?.charAt(0)}
                              </div>
                              <span className="font-medium text-ink-900">{emp.name}</span>
                            </div>
                          </td>
                          <td className="py-3 pr-4 text-ink-600">{emp.title || '-'}</td>
                          <td className="py-3 pr-4 text-ink-600">{getDeptName(emp.dept_id)}</td>
                          <td className="py-3 pr-4">
                            <span className="inline-block px-2 py-0.5 text-xs rounded-full bg-primary-50 text-primary-600 border border-primary-100">
                              {getLevelLabel(emp.level)}
                            </span>
                          </td>
                          <td className="py-3 pr-4 text-ink-400">{emp.email || '-'}</td>
                          <td className="py-3 text-right whitespace-nowrap">
                            <Button size="sm" type="ghost" onClick={() => handleEdit(emp, 'employee')}><Edit2 size={13} /></Button>
                            <Button size="sm" type="ghost" className="text-red-500! hover:bg-red-50!" onClick={() => handleDelete(emp.employee_id, 'employee')}><Trash2 size={13} /></Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          )}
        </div>
      </div>

      {showModal && (
        <ModalForm
          isOpen={showModal}
          onClose={() => setShowModal(false)}
          title={editingItem ? `编辑${modalType === 'department' ? '部门' : '员工'}` : `新建${modalType === 'department' ? '部门' : '员工'}`}
          initialValues={editingItem || {}}
          fields={modalFields}
          submitText={editingItem ? '更新' : '创建'}
          onSubmit={async (values) => {
            try {
              if (modalType === 'department') {
                if (editingItem) await updateDepartment(editingItem.dept_id, values);
                else await createDepartment(values);
              } else {
                if (editingItem) await updateEmployee(editingItem.employee_id, values);
                else await createEmployee(values);
              }
              setShowModal(false);
              loadData();
            } catch (err) {
              console.error('保存失败:', err);
            }
          }}
        />
      )}
    </div>
  );
}
