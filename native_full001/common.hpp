#pragma once
#include "../native001/json.hpp"
#include <arrow/api.h>
#include <arrow/compute/api.h>
#include <arrow/python/pyarrow.h>
#include <arrow/util/byte_size.h>
#include <pybind11/pybind11.h>
#include <functional>
#include <numeric>
#include <queue>
#include <unordered_map>
#include <unordered_set>
#include <deque>
#include <fstream>
#include <filesystem>

#ifndef RCWG_FULL_DIAGNOSTICS
#error RCWG_FULL_DIAGNOSTICS must be explicit
#endif
namespace full {
using rcwg::J; using rcwg::Fault; using rcwg::Parser; using rcwg::dump;
using Table=std::shared_ptr<arrow::Table>;
using Counts=std::map<std::string,int64_t>;
inline void count(Counts& c,const std::string& key,int64_t n=1) {
    if constexpr(RCWG_FULL_DIAGNOSTICS) c[key]+=n;
}
inline void ok(const arrow::Status& s){if(!s.ok())throw Fault("ARROW:"+s.ToString());}
template<class T>T take(arrow::Result<T> r){if(!r.ok())throw Fault("ARROW:"+r.status().ToString());return std::move(r).ValueOrDie();}
inline J scalar_value(const std::shared_ptr<arrow::Scalar>& s){
    if(!s->is_valid)return nullptr;
    switch(s->type->id()){
        case arrow::Type::INT64:return std::static_pointer_cast<arrow::Int64Scalar>(s)->value;
        case arrow::Type::DOUBLE:{double v=std::static_pointer_cast<arrow::DoubleScalar>(s)->value;if(!std::isfinite(v))throw Fault("NONFINITE");return v;}
        case arrow::Type::BOOL:return std::static_pointer_cast<arrow::BooleanScalar>(s)->value;
        case arrow::Type::STRING:return std::static_pointer_cast<arrow::StringScalar>(s)->value->ToString();
        case arrow::Type::LIST:{J::A values;auto array=std::static_pointer_cast<arrow::ListScalar>(s)->value;for(int64_t i=0;i<array->length();++i)values.push_back(scalar_value(take(array->GetScalar(i))));return values;}
        case arrow::Type::STRUCT:{J::O values;auto scalar=std::static_pointer_cast<arrow::StructScalar>(s);auto type=std::static_pointer_cast<arrow::StructType>(s->type);for(int i=0;i<type->num_fields();++i)values[type->field(i)->name()]=scalar_value(scalar->value[i]);return values;}
        case arrow::Type::NA:return nullptr;
        default:throw Fault("UNSUPPORTED_ARROW_TYPE");
    }
}
inline J cell(const Table& t,int col,int64_t i){
    if(col<0)throw Fault("FIELD_NOT_FOUND","plan");
    return scalar_value(take(t->column(col)->GetScalar(i)));
}
inline J field(const Table&t,int64_t i,const std::string& n){return cell(t,t->schema()->GetFieldIndex(n),i);}
inline int compare(const J&a,const J&b){
    if(a.null()||b.null())return a.null()?(b.null()?0:-1):1;
    if(a.number()&&b.number()){
        long double x=a.integer()?static_cast<long double>(a.i()):a.d(),y=b.integer()?static_cast<long double>(b.i()):b.d();
        return x<y?-1:x>y?1:0;
    }
    if(a.boolean()&&b.boolean())return int(a.b())-int(b.b());
    if(a.string()&&b.string())return a.str()<b.str()?-1:a.str()>b.str()?1:0;
    if(a.array()&&b.array())return dump(a)==dump(b)?0:dump(a)<dump(b)?-1:1;
    throw Fault("TYPE_MISMATCH","plan");
}
inline J arithmetic(const std::string& op,const J&a,const J&b){
    if(!a.number()||!b.number())throw Fault("TYPE_MISMATCH","plan");
    if(op=="div"){
        if(b.d()==0)throw Fault("DIVISION_BY_ZERO","plan");
        double result;
        if(a.integer()&&b.integer()){
            // Exact integer quotient, rounded once to nearest binary64, ties to even.
            // The scaled numerator needs at most 117 bits for any Int64 operands.
            auto magnitude=[](int64_t v)->uint64_t{return v<0?uint64_t(-(v+1))+1:uint64_t(v);};
            uint64_t n=magnitude(a.i()),d=magnitude(b.i());
            if(n==0)return 0.0;
            int e=(64-__builtin_clzll(n))-(64-__builtin_clzll(d));
            using U=unsigned __int128;
            if(e>=0?U(n)<(U(d)<<e):(U(n)<<(-e))<U(d))--e;
            int scale=52-e;U num=n,den=d;
            if(scale>=0)num<<=scale;else den<<=-scale;
            U q=num/den,r=num%den;
            if(r*2>den||(r*2==den&&(q&1)))++q;
            result=std::ldexp(double(uint64_t(q)),e-52);
            if((a.i()<0)!=(b.i()<0))result=-result;
        }else result=a.d()/b.d();
        if(!std::isfinite(result))throw Fault("ARITHMETIC_OVERFLOW","plan");return result;
    }
    if(a.integer()&&b.integer()){
        int64_t v;bool overflow;
        if(op=="add")overflow=__builtin_add_overflow(a.i(),b.i(),&v);
        else if(op=="sub")overflow=__builtin_sub_overflow(a.i(),b.i(),&v);
        else if(op=="mul")overflow=__builtin_mul_overflow(a.i(),b.i(),&v);
        else throw Fault("EXPRESSION_OPERATOR","plan");
        if(overflow)throw Fault("ARITHMETIC_OVERFLOW","plan");return v;
    }
    double v=op=="add"?a.d()+b.d():op=="sub"?a.d()-b.d():a.d()*b.d();
    if(!std::isfinite(v))throw Fault("ARITHMETIC_OVERFLOW","plan");return v;
}
using Lookup=std::function<J(const std::string&)>;
inline J eval(const J&a,const Lookup& get){
    if(a.has("literal"))return a.at("literal");if(a.has("field"))return get(a.at("field").str());
    auto op=a.at("op").str();
    if(op=="and"||op=="or"){
        bool unknown=false;for(auto& x:a.at("args").arr()){
            auto v=eval(x,get);if(v.null())unknown=true;
            else if(op=="and"&&!v.b())return false;
            else if(op=="or"&&v.b())return true;
        }return unknown?J(nullptr):J(op=="and");
    }
    if(op=="not"||op=="is_null"||op=="count"){
        auto v=eval(a.at("arg"),get);if(op=="is_null")return v.null();if(v.null())return nullptr;
        if(op=="not")return !v.b();if(v.string())return int64_t(rcwg::utf8_count(v.str()));if(v.array())return int64_t(v.arr().size());throw Fault("TYPE_MISMATCH","plan");
    }
    auto l=eval(a.at("left"),get),r=eval(a.at("right"),get);
    if(op=="in"){
        if(r.array()&&r.arr().empty())return false;if(l.null()||r.null())return nullptr;
        bool unknown=false;for(auto& v:r.arr()){if(v.null())unknown=true;else if(compare(l,v)==0)return true;}return unknown?J(nullptr):J(false);
    }
    if(l.null()||r.null())return nullptr;
    if(op=="eq")return compare(l,r)==0;if(op=="ne")return compare(l,r)!=0;
    if(op=="lt")return compare(l,r)<0;if(op=="le")return compare(l,r)<=0;
    if(op=="gt")return compare(l,r)>0;if(op=="ge")return compare(l,r)>=0;
    return arithmetic(op,l,r);
}
inline bool predicate(const Table&t,int64_t i,const J&p){auto v=eval(p,[&](auto&n){return field(t,i,n);});return !v.null()&&v.b();}
inline std::vector<int64_t> ordinals(int64_t n){std::vector<int64_t> v(n);std::iota(v.begin(),v.end(),0);return v;}
inline Table select(const Table&t,const std::vector<int64_t>& rows){
    arrow::Int64Builder b;ok(b.AppendValues(rows));auto indices=take(b.Finish());
    return take(arrow::compute::Take(t,indices)).table();
}
inline std::vector<int> columns(const Table&t,const J& names){
    std::vector<int> r;for(auto& n:names.arr()){int i=t->schema()->GetFieldIndex(n.str());if(i<0)throw Fault("FIELD_NOT_FOUND","plan");r.push_back(i);}return r;
}
inline std::string key(const Table&t,int64_t i,const std::vector<int>&cols,bool* null=nullptr){
    J::A values;for(auto c:cols){auto v=cell(t,c,i);if(v.null()&&null)*null=true;if(v.number()&&!v.integer()&&v.d()==0)v=J(0.0);values.push_back(v);}return dump(values);
}
inline J row(const Table&t,int64_t i){J::O r;for(int c=0;c<t->num_columns();++c)r[t->field(c)->name()]=cell(t,c,i);return r;}
inline void append_value(arrow::ArrayBuilder* b,const std::shared_ptr<arrow::DataType>&type,const J&v){
    if(v.null()){ok(b->AppendNull());return;}
    switch(type->id()){
        case arrow::Type::INT64:ok(static_cast<arrow::Int64Builder*>(b)->Append(v.i()));break;
        case arrow::Type::DOUBLE:ok(static_cast<arrow::DoubleBuilder*>(b)->Append(v.d()));break;
        case arrow::Type::BOOL:ok(static_cast<arrow::BooleanBuilder*>(b)->Append(v.b()));break;
        case arrow::Type::STRING:rcwg::utf8_count(v.str());ok(static_cast<arrow::StringBuilder*>(b)->Append(v.str()));break;
        case arrow::Type::LIST:{auto builder=static_cast<arrow::ListBuilder*>(b);auto list=std::static_pointer_cast<arrow::ListType>(type);ok(builder->Append());for(auto&item:v.arr())append_value(builder->value_builder(),list->value_type(),item);break;}
        case arrow::Type::STRUCT:{auto builder=static_cast<arrow::StructBuilder*>(b);auto structure=std::static_pointer_cast<arrow::StructType>(type);ok(builder->Append());for(int i=0;i<structure->num_fields();++i){auto f=structure->field(i);append_value(builder->field_builder(i),f->type(),v.at(f->name()));}break;}
        default:throw Fault("UNSUPPORTED_ARROW_TYPE");
    }
}
inline Table from_rows(const J::A& rows,const std::shared_ptr<arrow::Schema>& schema){
    std::vector<std::shared_ptr<arrow::Array>> arrays;
    for(auto& f:schema->fields()){
        auto b=take(arrow::MakeBuilder(f->type()));
        for(auto& r:rows)append_value(b.get(),f->type(),r.at(f->name()));
        arrays.push_back(take(b->Finish()));
    }return arrow::Table::Make(schema,arrays,int64_t(rows.size()));
}
struct Order {
    Table t;J keys;Counts* counts;
    bool operator()(int64_t a,int64_t b)const{
        count(*counts,"key_comparisons");
        for(auto& k:keys.arr()){
            auto x=field(t,a,k.at("field").str()),y=field(t,b,k.at("field").str());
            if(x.null()||y.null()){
                if(x.null()&&y.null())continue;
                bool first=k.has("nulls")&&k.at("nulls").str()=="first";return x.null()?first:!first;
            }
            int c=compare(x,y);if(c)return k.at("direction").str()=="asc"?c<0:c>0;
        }return a<b;
    }
};
inline J counts_json(const Counts& c){J::O o;for(auto&[k,v]:c)o[k]=v;return o;}
}
