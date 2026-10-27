package xiaozhi.modules.todo.dao;

import org.apache.ibatis.annotations.Mapper;

import xiaozhi.common.dao.BaseDao;
import xiaozhi.modules.todo.entity.TodoEventEntity;

@Mapper
public interface TodoEventDao extends BaseDao<TodoEventEntity> {
}
