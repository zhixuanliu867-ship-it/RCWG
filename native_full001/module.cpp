#include "relational.hpp"
#include "graph.hpp"
namespace py=pybind11;
using namespace full;

static Table unwrap(py::handle obj){return take(arrow::py::unwrap_table(obj.ptr()));}
static py::object wrap(const Table&t){auto p=arrow::py::wrap_table(t);if(!p)throw py::error_already_set();return py::reinterpret_steal<py::object>(p);}

PYBIND11_MODULE(RCWG_MODULE_NAME,m){
    if(arrow::py::import_pyarrow()!=0)throw py::error_already_set();
    m.attr("diagnostic")=bool(RCWG_FULL_DIAGNOSTICS);
    m.def("relational",[](const std::string&op,const std::string&impl,py::object data,py::object right,const std::string&params,const std::string&directory){
        auto t=unwrap(data);Table r=right.is_none()?nullptr:unwrap(right);auto p=Parser(params).parse();Counts c;Table out;
        {py::gil_scoped_release release;
            if(op=="filter")out=filtering(t,p.at("predicate"),impl=="vectorized",c);
            else if(op=="top_k")out=topk(t,p,impl=="streaming_heap",c);
            else if(op=="sort")out=sorting(t,p,impl=="external_merge",directory,c);
            else if(op=="deduplicate")out=dedup(t,p,impl=="hash",c);
            else if(op=="join")out=joining(t,r,p,impl,c);
            else if(op=="aggregate")out=aggregate(t,p,impl=="hash_group",c);
            else if(op=="project")out=projecting(t,p,impl=="copy",c);
            else throw Fault("UNSUPPORTED_IMPLEMENTATION");
        }
        return py::make_tuple(wrap(out),dump(counts_json(c)));
    });
    m.def("graph",[](const std::string&op,const std::string&impl,const std::string&graph,const std::string&seeds,const std::string&params){
        auto g=Parser(graph).parse(),s=Parser(seeds).parse(),p=Parser(params).parse();Counts c;J result;{py::gil_scoped_release release;result=graph_kernel(op,impl,g,s,p,c);}return py::make_tuple(dump(result),dump(counts_json(c)));
    });
    m.def("set_op",[](const std::string&left,const std::string&right,const std::string&mode,const std::string&impl){auto l=Parser(left).parse(),r=Parser(right).parse();Counts c;J result;{py::gil_scoped_release release;result=set_kernel(l,r,mode,impl=="hash",c);}return py::make_tuple(dump(result),dump(counts_json(c)));});
    m.def("dense",[](const std::string&docs,const std::string&query,const std::string&params){auto d=Parser(docs).parse(),q=Parser(query).parse(),p=Parser(params).parse();Counts c;J result;{py::gil_scoped_release release;result=dense(d,q,p,c);}return py::make_tuple(dump(result),dump(counts_json(c)));});
    m.def("expression",[](const std::string&ast,const std::string&record){auto a=Parser(ast).parse(),r=Parser(record).parse();J result;{py::gil_scoped_release release;result=eval(a,[&](const std::string&n){return r.at(n);});}return dump(result);});
}
