#pragma once
#include "common.hpp"
namespace full {
// Unicode token boundaries/casefolding are supplied by the frozen public
// tokenizer. Frequency accumulation, inverted postings and BM25 scoring are native.
class Bm25Index {
    std::vector<J> ids_;
    std::vector<int64_t> lengths_;
    std::unordered_map<std::string,std::vector<std::pair<size_t,int64_t>>> postings_;
    double average_=0;
    Counts construction_;
public:
    explicit Bm25Index(const J&documents) {
        std::unordered_set<std::string> seen;int64_t sum=0;
        for(auto&doc:documents.arr()) {
            auto id=doc.at("document_id");if(!seen.insert(dump(id)).second)throw Fault("DOCUMENT_ID_DUPLICATE");
            size_t ordinal=ids_.size();ids_.push_back(id);auto&tokens=doc.at("tokens").arr();lengths_.push_back(tokens.size());
            if(__builtin_add_overflow(sum,int64_t(tokens.size()),&sum))throw Fault("ARITHMETIC_OVERFLOW");
            std::unordered_map<std::string,int64_t> frequencies;
            for(auto&term:tokens){++frequencies[term.str()];count(construction_,"index_tokens");}
            for(auto&[term,frequency]:frequencies)postings_[term].push_back({ordinal,frequency});
        }
        if(!ids_.empty())average_=double(sum)/double(ids_.size());
        count(construction_,"index_documents",ids_.size());count(construction_,"index_terms",postings_.size());
    }
    std::pair<J,Counts> query(const J&tokens,int64_t limit,int64_t offset) const {
        if(limit<0||offset<0)throw Fault("PARAMETER_RANGE","plan");
        Counts counts;std::vector<double> scores(ids_.size(),0.0);std::map<std::string,int64_t> terms;
        for(auto&term:tokens.arr())++terms[term.str()];
        for(auto&[term,qf]:terms) {
            auto found=postings_.find(term);if(found==postings_.end())continue;
            auto&postings=found->second;double idf=std::log1p((double(ids_.size())-double(postings.size())+.5)/(double(postings.size())+.5));
            for(auto[ordinal,frequency]:postings) {
                double denominator=double(frequency)+1.2*(.25+.75*double(lengths_[ordinal])/average_);
                scores[ordinal]+=double(qf)*idf*double(frequency)*2.2/denominator;count(counts,"postings_scored");
                if(!std::isfinite(scores[ordinal]))throw Fault("ARITHMETIC_OVERFLOW");
            }
        }
        auto order=ordinals(ids_.size());std::sort(order.begin(),order.end(),[&](int64_t a,int64_t b){count(counts,"ranking_comparisons");return scores[a]!=scores[b]?scores[a]>scores[b]:compare(ids_[a],ids_[b])<0;});
        J::A rows;auto begin=std::min<int64_t>(offset,order.size());auto end=begin+std::min<int64_t>(limit,int64_t(order.size())-begin);
        for(auto i=begin;i<end;++i){auto ordinal=order[i];rows.push_back(J::O{{"document_id",ids_[ordinal]},{"score",scores[ordinal]}});}
        count(counts,"documents_ranked",ids_.size());return {rows,counts};
    }
    Counts construction() const {return construction_;}
};
}
