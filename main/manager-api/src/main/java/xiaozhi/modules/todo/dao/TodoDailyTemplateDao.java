package xiaozhi.modules.todo.dao;

import org.apache.ibatis.annotations.Mapper;

import xiaozhi.common.dao.BaseDao;
import xiaozhi.modules.todo.entity.TodoDailyTemplateEntity;

@Mapper
public interface TodoDailyTemplateDao extends BaseDao<TodoDailyTemplateEntity> {
}
