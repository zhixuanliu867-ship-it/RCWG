#include "relational.hpp"
#include "graph.hpp"
#include "stream_aggregate.hpp"
#include "text.hpp"
#include "bounded.hpp"
#include "sorted_relational.hpp"
namespace py=pybind11;
using namespace full;

static Table unwrap(py::handle obj){return take(arrow::py::unwrap_table(obj.ptr()));}
static py::object wrap(const Table&t){auto p=arrow::py::wrap_table(t);if(!p)throw py::error_already_set();return py::reinterpret_steal<py::object>(p);}

PYBIND11_MODULE(RCWG_MODULE_NAME,m){
    if(arrow::py::import_pyarrow()!=0)throw py::error_already_set();
    // Local to this extension: never reinterpret unrelated RuntimeError values.
    py::register_local_exception_translator([](std::exception_ptr error){
        try { if(error) std::rethrow_exception(error); }
        catch(const Fault& fault){
            auto cls=py::module_::import("rcwg_full.runtime.errors").attr("ExecutionFault");
            auto value=cls(fault.what(),fault.attribution);
            value.attr("origin")="native";
            value.attr("stage")="NATIVE_KERNEL";
            PyErr_SetObject(cls.ptr(),value.ptr());
        }
    });
    m.attr("diagnostic")=bool(RCWG_FULL_DIAGNOSTICS);
    m.def("sorted_group_file",[](const std::string&input,const std::string&params,const std::string&directory){
        auto p=Parser(params).parse();std::tuple<std::string,int64_t,Counts> result;
        {py::gil_scoped_release release;result=sorted_group_file(input,p,directory);}
        return py::make_tuple(std::get<0>(result),std::get<1>(result),dump(counts_json(std::get<2>(result))));});
    m.def("sorted_join_files",[](const std::string&left,const std::string&right,const std::string&params,const std::string&directory){
        auto p=Parser(params).parse();std::tuple<std::string,int64_t,Counts> result;
        {py::gil_scoped_release release;result=sorted_join_files(left,right,p,directory);}
        return py::make_tuple(std::get<0>(result),std::get<1>(result),dump(counts_json(std::get<2>(result))));});
    py::class_<StreamTopK,std::shared_ptr<StreamTopK>>(m,"StreamTopK",py::module_local())
        .def(py::init([](py::object empty,const std::string&params){return std::make_shared<StreamTopK>(unwrap(empty),Parser(params).parse());}))
        .def("consume",[](StreamTopK&state,py::object data){auto batch=unwrap(data);py::gil_scoped_release release;state.consume(batch);})
        .def("finish",[](StreamTopK&state){std::pair<Table,Counts> result;{py::gil_scoped_release release;result=state.finish();}return py::make_tuple(wrap(result.first),dump(counts_json(result.second)));});
    py::class_<StreamSort,std::shared_ptr<StreamSort>>(m,"StreamSort",py::module_local())
        .def(py::init([](py::object empty,const std::string&params,const std::string&directory){return std::make_shared<StreamSort>(unwrap(empty),Parser(params).parse(),directory);}))
        .def("consume",[](StreamSort&state,py::object data){auto batch=unwrap(data);py::gil_scoped_release release;state.consume(batch);})
        .def("finish",[](StreamSort&state){std::pair<std::string,Counts> result;{py::gil_scoped_release release;result=state.finish();}return py::make_tuple(result.first,state.rows(),dump(counts_json(result.second)));});
    py::class_<Bm25Index,std::shared_ptr<Bm25Index>>(m,"Bm25Index",py::module_local())
        .def(py::init([](const std::string&documents){auto docs=Parser(documents).parse();py::gil_scoped_release release;return std::make_shared<Bm25Index>(docs);}))
        .def("query",[](const Bm25Index&index,const std::string&tokens,int64_t limit,int64_t offset){auto terms=Parser(tokens).parse();std::pair<J,Counts> result;{py::gil_scoped_release release;result=index.query(terms,limit,offset);}return py::make_tuple(dump(result.first),dump(counts_json(result.second)));})
        .def("construction",[](const Bm25Index&index){return dump(counts_json(index.construction()));});
    py::class_<StreamAggregate,std::shared_ptr<StreamAggregate>>(m,"StreamAggregate",py::module_local())
        .def(py::init([](py::object empty,const std::string&params){return std::make_shared<StreamAggregate>(unwrap(empty),Parser(params).parse());}))
        .def("consume",[](StreamAggregate&state,py::object data){auto batch=unwrap(data);py::gil_scoped_release release;state.consume(batch);})
        .def("finish",[](StreamAggregate&state){std::pair<Table,Counts> result;{py::gil_scoped_release release;result=state.finish();}return py::make_tuple(wrap(result.first),dump(counts_json(result.second)));});
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
